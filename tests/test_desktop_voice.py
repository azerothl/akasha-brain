from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from akasha_brain import desktop_voice as voice
from akasha_brain.project_common import ProjectError


def test_import_uses_g7_file_checks_and_silence(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("AKASHA_WHISPER_CACHE", str(tmp_path / "cache"))
    request = voice.VoiceRequest(project)
    with wave.open(str(project / "silence.wav"), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", ""))
        stream.writeframes(bytes(32000))
    assert request.transcribe(project, "silence.wav")["text"] == ""
    with pytest.raises(ProjectError, match="interdit"):
        request.transcribe(project, "../silence.wav")


@pytest.mark.parametrize("outcome", ["ok", "cancel", "failure"])
def test_temporary_capture_is_removed_after_every_outcome(tmp_path, monkeypatch, outcome):
    request = voice.VoiceRequest(tmp_path)
    pcm = b"\x01\x00" * 16000
    files = []

    def recognize(folder, name, checkpoint, *, ask, progress):
        files.append(folder / name)
        assert not folder.is_relative_to(tmp_path)
        with wave.open(str(files[0]), "rb") as stream:
            assert stream.getparams()[:3] == (1, 2, 16000)
            assert stream.readframes(stream.getnframes()) == pcm
        if outcome == "failure":
            raise ValueError("audio")
        if outcome == "cancel":
            request.cancelled.set()
        return {"text": "Une demande."}

    monkeypatch.setattr(voice.whisper_pilot, "transcribe", recognize)
    buffer = request.pcm = bytearray(pcm)
    if outcome == "ok":
        assert request.from_capture()["text"] == "Une demande."
    else:
        with pytest.raises(InterruptedError if outcome == "cancel" else ValueError):
            request.from_capture()
    assert not files[0].parent.exists()
    assert not any(buffer)


def test_cancelling_queued_dictation_wipes_audio_before_engine_starts():
    request = voice.VoiceRequest(None)
    buffer = request.pcm = bytearray(b"audio")
    request.cancel()
    assert not any(buffer)
    with pytest.raises(InterruptedError):
        request.from_capture()


def test_replaced_project_rejects_queued_request(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    request = voice.VoiceRequest(project)
    project.rename(tmp_path / "original")
    project.mkdir()
    engine = Mock()
    monkeypatch.setattr(voice.whisper_pilot, "transcribe", engine)
    with pytest.raises(ValueError, match="changé"):
        request.transcribe(project, "a.wav")
    engine.assert_not_called()


@pytest.mark.parametrize("decision", ["accept", "decline", "cancel", "leave"])
def test_g7_decision_belongs_to_one_request(decision):
    request = voice.VoiceRequest(None)
    review = SimpleNamespace(expires_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
    with ThreadPoolExecutor() as pool:
        job = pool.submit(request.approve, review)
        item, answer = request.updates.get(timeout=2)
        assert item is review
        if decision == "leave":
            request.cancelled.set()
            with pytest.raises(InterruptedError):
                job.result(timeout=2)
        else:
            answer.set_result(decision)
            assert job.result(timeout=2) == decision


def test_expired_artifact_consent_is_rejected():
    with pytest.raises(ProjectError, match="expir"):
        voice.VoiceRequest(None).approve(SimpleNamespace(expires_at="2000-01-01T00:00:00+00:00"))


@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def desktop(tmp_path, tk_root):
    import tkinter as tk
    from akasha_brain.desktop_sessions import ConversationWorkspace
    from akasha_brain.desktop_tasks import NotesTasks

    window = tk.Toplevel(tk_root)
    tasks = NotesTasks(tmp_path / "runs", None, None, False)
    project = tmp_path / "project"
    project.mkdir()
    workspace = ConversationWorkspace(window, None, None, None, None, tasks, project=project, review_prepared=None)
    window.update()
    try:
        yield window, workspace
    finally:
        window.destroy()


def test_microphone_requires_consent_handles_device_refusal_and_cancels(desktop, monkeypatch):
    _, workspace = desktop
    composer = workspace.current.voice
    opened = Mock(side_effect=[PermissionError("Micro refusé par Windows"), Mock()])
    monkeypatch.setattr(voice, "Microphone", opened)
    monkeypatch.setattr(voice.messagebox, "askyesno", Mock(side_effect=[False, True, True]))
    composer.record.invoke()
    assert "refusé" in composer.status.get()
    opened.assert_not_called()
    composer.record.invoke()
    assert "refusé par Windows" in composer.status.get()
    assert composer.request is None
    composer.record.invoke()
    mic = composer.mic
    composer.cancel_button.invoke()
    mic.close.assert_called_once_with()
    assert composer.job is composer.request is composer.timer is None
    assert workspace.current.entry.get() == ""


def test_voice_import_refuses_cold_g7_download_in_desktop(desktop, monkeypatch, tmp_path):
    window, workspace = desktop
    pane = workspace.current
    source = pane.project / "message.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", ""))
        stream.writeframes(b"\x01\x00" * 16000)
    cache = tmp_path / "empty-whisper"
    monkeypatch.setenv("AKASHA_WHISPER_CACHE", str(cache))
    monkeypatch.setattr(voice.filedialog, "askopenfilename", lambda **_: str(source))
    decline = Mock(return_value=False)
    monkeypatch.setattr(voice.messagebox, "askyesnocancel", decline)
    pane.voice.import_button.invoke()
    deadline = time.monotonic() + 5
    while pane.voice.job is not None and time.monotonic() < deadline:
        window.update()
        time.sleep(.01)
    assert pane.voice.job is None
    decline.assert_called_once()
    assert "SHA-256" in decline.call_args.args[1]
    assert "refusé" in pane.voice.status.get()
    assert not pane.entry.get() and pane.conversation_plan is None
    assert not list(cache.glob("*.zip"))


def test_session_switch_releases_capture_and_late_result(desktop, monkeypatch):
    window, workspace = desktop
    first = workspace.current
    monkeypatch.setattr(voice, "Microphone", Mock())
    monkeypatch.setattr(voice.messagebox, "askyesno", Mock(return_value=True))
    first.voice.record.invoke()
    mic = first.voice.mic
    workspace.new()
    window.update()
    mic.close.assert_called_once_with()
    assert first.voice.request is None and workspace.current.entry.get() == ""
    workspace.select(first.session_record.id)
    window.update()
    pending = Future()
    pending.set_running_or_notify_cancel()
    monkeypatch.setattr(first.tasks.scheduler, "submit", lambda _: pending)
    monkeypatch.setattr(voice.filedialog, "askopenfilename", lambda **_: str(first.project / "message.wav"))
    first.voice.import_button.invoke()
    workspace.new()
    window.update()
    pending.set_result({"text": "Brouillon périmé"})
    workspace.select(first.session_record.id)
    window.update()
    assert first.voice.job is None and first.entry.get() == ""


def test_edit_erase_project_change_and_explicit_send(desktop, monkeypatch, tmp_path):
    _, workspace = desktop
    pane = workspace.current
    composer = pane.voice
    source = pane.project / "message.flac"
    monkeypatch.setattr(voice.filedialog, "askopenfilename", lambda **_: str(source))
    monkeypatch.setattr(voice.whisper_pilot, "transcribe", lambda *_a, **_kw: {"text": "Texte dicté"})
    initial = pane.transcript.get("1.0", "end")

    def import_voice():
        composer.import_button.invoke()
        composer.job.result(timeout=2)
        composer.bar.after_cancel(composer.timer)
        composer.poll()

    pane.entry.insert(0, "Début")
    import_voice()
    assert pane.entry.get() == "Début Texte dicté"
    pane.entry.insert("end", " corrigé")
    assert pane.transcript.get("1.0", "end") == initial
    composer.erase_button.invoke()
    assert pane.entry.get() == ""
    import_voice()
    pane.entry.delete(0, "end")
    pane.entry.insert(0, "Brouillon entièrement réécrit")
    other = tmp_path / "other"
    other.mkdir()
    pane.select_project(other)
    assert pane.entry.get() == ""
    composer.import_button.invoke()
    assert "projet actif" in composer.status.get() and composer.job is None
    pane.select_project(source.parent)
    import_voice()
    pane.entry.insert("end", " corrigé")
    pane.send()
    assert "Vous\nTexte dicté corrigé\n" in pane.transcript.get("1.0", "end")
    assert not composer.draft and pane.entry.get() == ""
