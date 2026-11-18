import json
import wave

import pytest

from akasha_brain import whisper_pilot as pilot
from akasha_brain.conversation_planning import execute_intents, explicit_media_step, load_conversation_catalog, references
from akasha_brain.project_common import ProjectError
from contracts.akasha_contracts.errors import ErrorCode


def test_uncertainty_is_local_and_visible():
    def segment(text, p, start, end):
        return {"text": text, "offsets": {"from": start, "to": end},
                "tokens": [{"id": 123, "text": text, "p": p}, {"id": 50365, "text": "[_TT_1]", "p": 0.01}]}
    items = [segment("Ottawa", .93, 0, 800), segment("Toginet", .33, 800, 1400), segment("...", .20, 1400, 1500)]
    segments = pilot.decode(json.dumps({"transcription": items}).encode(), 1500)
    assert [(s["text"], s["uncertain"]) for s in segments] == [("Ottawa", False), ("Toginet", True)]
    text = pilot.display({"segments": segments})
    assert "À vérifier : Toginet" in text and "À vérifier : Ottawa" not in text
    items[1]["offsets"]["from"] = 200
    with pytest.raises(ProjectError):
        pilot.decode(json.dumps({"transcription": items}).encode(), 1500)


def test_conversation_silence_and_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "cache_path", lambda: tmp_path)
    project = tmp_path/"project"
    project.mkdir()
    with wave.open(str(project/"vide.wav"), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", ""))
        out.writeframes(bytes(32000))

    def ask(request):
        refs = references(request)
        return execute_intents(request, explicit_media_step(request, refs), refs, project, load_conversation_catalog())[0]

    reply = ask("Transcris vide.wav")
    assert reply.output["status"] == "silence" and reply.output["text"] == "" and reply.output["segments"] == []
    assert reply.plan.goal["risk_class"] == "R1"
    assert ask("Transcris ../vide.wav").code == ErrorCode.PERMISSION_DENIED
    (project/"cassé.flac").write_bytes(b"not flac")
    assert ask("Transcris cassé.flac").code == ErrorCode.CONTRACT_PRECONDITION_FAILED


@pytest.mark.parametrize("scores,end,flag", [
    ([.50, 1., 1.], 1000, False), ([.49, 1., 1.], 1000, True),
    ([.79, .79], 1000, True), ([.8], 1000, False), ([.9], 1010, True), ([], 1000, True),
])
def test_server_and_cpu_have_identical_alerts(scores, end, flag):
    native = {"text": "parole", "offsets": {"from": 0, "to": end},
              "tokens": [{"text": "son", "id": 12, "p": p} for p in scores]}
    server = {"text": "parole", "start": 0, "end": end/1000, "tokens": [12]*len(scores),
              "words": [{"word": "son", "probability": p} for p in scores]}
    gpu = pilot.decode(json.dumps({"segments": [server]}).encode(), 1000, server=True)
    assert gpu == pilot.decode(json.dumps({"transcription": [native]}).encode(), 1000)
    assert gpu[0]["uncertain"] is flag


def test_gpu_token_mismatch_is_rejected():
    raw = {"segments": [{"text": "parole", "start": 0, "end": 1, "words": [], "tokens": [1]}]}
    with pytest.raises(ProjectError):
        pilot.decode(json.dumps(raw).encode(), 1000, server=True)


@pytest.mark.parametrize("failure,should_fallback", [
    (pilot.whisper_resident.GpuUnavailable("cuda_inference"), True),
    (InterruptedError("Annulation"), False),
])
def test_only_unavailable_gpu_replays_on_cpu(tmp_path, monkeypatch, failure, should_fallback):
    from contextlib import nullcontext
    project = tmp_path/"project"
    project.mkdir()
    with wave.open(str(project/"audio.wav"), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", ""))
        stream.writeframes(b"\x01\x00"*320)
    monkeypatch.setattr(pilot, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(pilot.whisper_resident, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(pilot, "reserve_model", lambda *a, **kw: nullcontext())

    def unavailable(*args):
        raise failure

    cpu_calls = []
    monkeypatch.setattr(pilot.whisper_resident, "transcribe", unavailable)
    monkeypatch.setattr(pilot, "cpu_transcribe", lambda *args: cpu_calls.append(args) or [])
    if should_fallback:
        result = pilot.transcribe(project, "audio.wav")
        assert result["execution"] == {"device": "cpu", "reused": False, "fallback_reason": "cuda_inference"}
        assert len(cpu_calls) == 1
    else:
        with pytest.raises(InterruptedError):
            pilot.transcribe(project, "audio.wav")
        assert not cpu_calls


def test_idle_watcher_rechecks_session_under_lease(monkeypatch):
    from contextlib import nullcontext
    resident = pilot.whisper_resident
    clock = [0.]
    ticket = {"sandbox": "guest-a", "used": 0.}
    released = []
    monkeypatch.setattr(resident, "read_ticket", lambda: ticket)
    monkeypatch.setattr(resident, "time", lambda: clock[0])
    monkeypatch.setattr(resident, "sleep", lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    monkeypatch.setattr(resident, "inference_lease", nullcontext)
    monkeypatch.setattr(resident, "release", lambda current: released.append((current["sandbox"], clock[0])))
    resident.expire("old-guest")
    assert not released
    resident.expire("guest-a")
    assert released == [("guest-a", resident.IDLE_SECONDS)]
