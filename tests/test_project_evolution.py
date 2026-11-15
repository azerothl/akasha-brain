from contextlib import closing
import json
import sqlite3
import sys
from uuid import uuid4

import pytest

from akasha_brain import project
from akasha_brain.evolution_consent import grant, revoke
from akasha_brain.project_backup import backup, grant_backup, restore, revoke_backup
from akasha_brain.project_backup_vault import decode, encode, vault_path
from akasha_brain.project_common import ProjectError, project_scope
from akasha_brain.project_evolution import collect, content_path, erase, request_erasure


@pytest.fixture
def prepared_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_bytes(b"value = 1\n")
    (root / "check.py").write_bytes(b"from app import value\nassert value == 2\n")
    replacement = tmp_path / "candidate.py"
    replacement.write_bytes(b"value = 2\n")
    proposal = tmp_path / "proposal"

    def validate(stage, runtime, *, checkpoint=None):
        if checkpoint is not None:
            checkpoint()
        assert b"+value = 2\n" in (stage / "proposal.diff").read_bytes()
        assert (stage / "snapshot/app.py").read_bytes() == b"value = 1\n"
        return {"status": "passed", "guest_exit_code": 0x4700, "read_only_input": True,
                "sandbox_stopped": True, "sandbox_id": str(uuid4())}

    monkeypatch.setattr(project, "validate_in_sandbox", validate)
    receipt = project.prepare(root, proposal, "app.py", replacement, "check.py", tmp_path)
    return root, proposal, tmp_path / "evolution.db", receipt["approval_sha256"]


def test_denied_collection_does_not_read_or_copy_the_artifact(prepared_project, monkeypatch):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code"])["consent_id"]
    read_bytes = type(proposal).read_bytes

    def forbid_payload(path):
        assert path.name not in ("replacement.txt", "proposal.diff")
        return read_bytes(path)

    monkeypatch.setattr(type(proposal), "read_bytes", forbid_payload)
    for category, scope, attestation, reason in (
        ("source_code", None, approval, "consent_missing"),
        ("diffs", consent, approval, "consent_scope_mismatch"),
        ("source_code", consent, None, "data_excluded"),
    ):
        with pytest.raises(ProjectError) as error:
            collect(root, proposal, registry, category, scope, attestation)
        assert error.value.error.details["reason"] == reason
        assert not registry.with_name(registry.name + ".project-content.sqlite").exists()


@pytest.mark.parametrize("category", ["source_code", "diffs"])
def test_reuse_validated_artifact_and_refuse_after_revoke(prepared_project, tmp_path, category):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), [category])["consent_id"]
    sample = collect(root, proposal, registry, category, consent, approval)
    output = tmp_path / "reuse"
    result = project.reuse(root, registry, sample["sample_id"], category, output, tmp_path)
    assert result["status"] == "reused"
    assert json.loads((output / "report.json").read_bytes()) == result
    assert list(output.iterdir()) == [output / "report.json"]
    assert (root / "app.py").read_bytes() == b"value = 1\n"

    revoke(registry, consent)
    output = tmp_path / "blocked"
    with pytest.raises(ProjectError) as error:
        project.reuse(root, registry, sample["sample_id"], category, output, tmp_path)
    assert error.value.error.details["reason"] == "consent_revoked"
    assert not output.exists()


def test_revocation_during_validation_blocks_reuse_result(prepared_project, tmp_path, monkeypatch):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code"])["consent_id"]
    sample = collect(root, proposal, registry, "source_code", consent, approval)
    original = project.validate_in_sandbox

    def revoke_during_validation(stage, runtime, *, checkpoint=None):
        result = original(stage, runtime, checkpoint=checkpoint)
        revoke(registry, consent)
        return result

    monkeypatch.setattr(project, "validate_in_sandbox", revoke_during_validation)
    output = tmp_path / "revoked"
    with pytest.raises(ProjectError) as error:
        project.reuse(root, registry, sample["sample_id"], "source_code", output, tmp_path)
    assert error.value.error.details["reason"] == "consent_revoked"
    assert not list(output.iterdir())


def test_erasure_blocks_siblings_before_deleting_copies_and_reports(prepared_project, tmp_path):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code", "diffs"])["consent_id"]
    samples = [collect(root, proposal, registry, category, consent, approval) for category in ("source_code", "diffs")]
    source, diff = samples
    output = tmp_path / "replayed"
    project.reuse(root, registry, diff["sample_id"], "diffs", output, tmp_path)
    request = request_erasure(root, registry, source["sample_id"])
    assert request["status"] == "pending" and request["blocked_copies"] == 2
    assert (output / "report.json").is_file()
    contents = content_path(root, registry)
    with closing(sqlite3.connect(contents)) as db:
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone() == (2,)
    for sample in samples:
        with pytest.raises(ProjectError) as error:
            project.reuse(root, registry, sample["sample_id"], sample["category"], tmp_path / "blocked", tmp_path)
        assert error.value.error.details["reason"] == "content_erasure_requested"

    result = erase(root, registry, source["sample_id"])
    assert result == {"request_id": request["request_id"], "status": "erased", "copies_erased": 2, "reports_removed": 1}
    with closing(sqlite3.connect(contents)) as db:
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM project_replays").fetchone() == (0,)
    assert not (output / "report.json").exists()
    with pytest.raises(ProjectError) as error:
        collect(root, proposal, registry, "source_code", consent, approval)
    assert error.value.error.details["reason"] == "content_erasure_requested"
    assert erase(root, registry, diff["sample_id"])["status"] == "erased"
    assert (root / "app.py").read_bytes() == b"value = 1\n"


def test_erasure_during_replay_stays_pending_until_the_safe_point(prepared_project, tmp_path, monkeypatch):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code"])["consent_id"]
    sample_id = collect(root, proposal, registry, "source_code", consent, approval)["sample_id"]
    original = project.validate_in_sandbox

    def erase_during_validation(stage, runtime, *, checkpoint=None):
        result = original(stage, runtime, checkpoint=checkpoint)
        pending = erase(root, registry, sample_id)
        assert pending["status"] == "pending" and pending["reason"] == "replay_in_progress"
        return result

    monkeypatch.setattr(project, "validate_in_sandbox", erase_during_validation)
    output = tmp_path / "running"
    with pytest.raises(ProjectError) as error:
        project.reuse(root, registry, sample_id, "source_code", output, tmp_path)
    assert error.value.error.details["reason"] == "content_erasure_requested"
    assert not list(output.iterdir())
    assert erase(root, registry, sample_id)["status"] == "erased"


def test_changed_report_keeps_erasure_pending_and_never_deletes_the_replacement(prepared_project, tmp_path):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code"])["consent_id"]
    sample_id = collect(root, proposal, registry, "source_code", consent, approval)["sample_id"]
    output = tmp_path / "replayed"
    project.reuse(root, registry, sample_id, "source_code", output, tmp_path)
    report = output / "report.json"
    original = report.read_bytes()
    report.write_bytes(b"user replacement")

    pending = erase(root, registry, sample_id)
    assert pending["status"] == "pending" and pending["reason"] == "copy_unreachable"
    assert report.read_bytes() == b"user replacement"
    with pytest.raises(ProjectError) as error:
        project.reuse(root, registry, sample_id, "source_code", tmp_path / "blocked", tmp_path)
    assert error.value.error.details["reason"] == "content_erasure_requested"

    report.write_bytes(original)
    completed = erase(root, registry, sample_id)
    assert completed["status"] == "erased" and completed["request_id"] == pending["request_id"]
    assert not report.exists()


def test_backup_needs_its_own_consent_before_creating_files(prepared_project, tmp_path):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code"])["consent_id"]
    collect(root, proposal, registry, "source_code", consent, approval)
    output = tmp_path / "local.backup"
    for offered in (None, consent):
        with pytest.raises(ProjectError) as error:
            backup(root, registry, output, offered)
        assert error.value.error.details["reason"] == "backup_consent_missing"
        assert not output.exists() and not vault_path(root, registry).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Le coffre utilise DPAPI Windows.")
def test_backup_filters_categories_and_authenticates_its_ciphertext(prepared_project, tmp_path):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["source_code", "diffs"])["consent_id"]
    for category in ("source_code", "diffs"):
        collect(root, proposal, registry, category, consent, approval)
    backup_id = grant_backup(root, registry, ["source_code"])["consent_id"]
    archive = tmp_path / "local.backup"
    result = backup(root, registry, archive, backup_id)
    assert result["copies"] == 1
    before = content_path(root, registry).read_bytes()
    envelope = json.loads(archive.read_bytes())
    tag = decode(envelope["index"]["tag"])
    envelope["index"]["tag"] = encode(bytes([tag[0] ^ 1]) + tag[1:])
    tampered = tmp_path / "tampered.backup"
    tampered.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ProjectError) as error:
        restore(root, registry, tampered)
    assert error.value.error.details["reason"] == "key_unavailable"
    assert content_path(root, registry).read_bytes() == before

    revoke_backup(root, registry, backup_id)
    with pytest.raises(ProjectError) as error:
        restore(root, registry, archive)
    assert error.value.error.details["reason"] == "backup_consent_inactive"
