import json
import sqlite3
from types import SimpleNamespace

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from akasha_brain import capability_recovery, ocr_recovery
from akasha_brain.capability_recovery import Recovery
from akasha_brain.conversation_planning import execute_intents, explicit_media_step, load_conversation_catalog, references
from akasha_brain.notes_sandbox import CHANNELS


PROOF = {"status": "passed", "sandbox_stopped": True, "read_only_input": True, "guest_exit_code": 0x4700,
         "channel_probe": 0x410F, "disabled_channels": list(CHANNELS)}


def ask(state, request, project):
    refs = references(request)
    return execute_intents(request, explicit_media_step(request, refs), refs, project, load_conversation_catalog(),
                           recovery=state)[0]


def report(state, capability):
    with sqlite3.connect(state.database) as db:
        row = db.execute("SELECT report FROM gap_reports WHERE capability = ?", (capability,)).fetchone()
    return json.loads(row[0])


def test_discover_qualify_resume_and_reuse_same_capability(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    image = b"\x89PNG\r\n\x1a\n" + b"test-bytes"
    (project / "capture.png").write_bytes(image)
    candidate = ocr_recovery.Candidate(tmp_path / "runtime", {}, "fixture-sha256")
    calls, messages = [], []

    def run(provider, stopped, data=None):
        assert provider == candidate and not stopped()
        calls.append(data)
        return {**PROOF, **({"exported": "ALPHA 35"} if data is not None else {})}

    adapter = SimpleNamespace(MANIFEST=ocr_recovery.MANIFEST, discover=lambda runtime: candidate,
                              read_input=ocr_recovery.read_input, run=run)
    monkeypatch.setitem(capability_recovery.PROVIDERS, "image.ocr", adapter)
    database = tmp_path / "registry.sqlite"
    state = Recovery(database, None, messages.append, lambda: False)
    request = "Lis le texte de « capture.png »"
    result = ask(state, request, project)
    assert result.plan.goal["risk_class"] == "R1"
    assert result.output == "ALPHA 35" and calls == [None, image]
    first = report(state, "image.ocr")
    assert first["events"] == ["missing", "local_discovery", "candidate", "qualification", "activated", "resumed"]
    assert request not in str(first) and "capture.png" not in str(first) and "ALPHA 35" not in str(first)

    reopened = Recovery(database, None, messages.append, lambda: False)
    assert ask(reopened, request, project).output == "ALPHA 35"
    assert calls == [None, image, image]
    assert report(reopened, "image.ocr")["events"] == ["reused", "resumed"]

    adapter.run = lambda *args: {**PROOF, "read_only_input": False, "exported": "no proof"}
    failure = ask(reopened, request, project)
    assert isinstance(failure, AkashaError) and failure.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED
    assert reopened.stored("image.ocr") is None
    assert report(reopened, "image.ocr")["events"] == ["reused", "rolled_back"]


def test_missing_generator_is_investigated_without_activating_a_different_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(capability_recovery, "installed_image_engines", lambda: [])
    state = Recovery(tmp_path / "registry.sqlite", None, lambda text: None, lambda: False)
    error = ask(state, "est ce que tu peux me générer une image d'un chat devant un miroir ?", None)
    assert error.code == ErrorCode.CAPABILITY_UNAVAILABLE and error.details["recovery"] == "waiting"
    assert report(state, "image.generate")["reason"] == "no_supported_image_engine_detected"
    assert state.stored("image.ocr") is None
    assert explicit_media_step("Explique comment générer une image", []) is None
    assert explicit_media_step("Lis le texte de guide.md", ["guide.md"]) is None


def test_out_of_scope_image_cannot_start_a_candidate(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    other = tmp_path / "outside.png"
    other.touch()
    state = Recovery(tmp_path / "registry.sqlite", None, lambda text: None, lambda: False)
    error = ask(state, f'Lis le texte de « {other} »', project)
    assert error.code == ErrorCode.PERMISSION_DENIED and not state.database.exists()
