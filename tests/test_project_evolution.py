from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

import pytest

from akasha_brain import project
from akasha_brain import daily_backup
from akasha_brain import project_backup as backup_module
from akasha_brain.evolution_consent import grant, revoke
from akasha_brain.planning import PlanningError
from akasha_brain.project_audit import LOG_NAME, verify as verify_audit
from akasha_brain.project_backup import backup, grant_backup, restore, revoke_backup
from akasha_brain.project_backup_vault import decode, encode, vault_path
from akasha_brain.project_common import ProjectError, project_scope
from akasha_brain.project_data import ProjectData
from akasha_brain.project_evolution import collect, content_path, erase, expire_copies, request_erasure


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
    log = registry.parent / LOG_NAME
    assert verify_audit(log) == {"status": "passed", "entries_verified": 3}
    with closing(sqlite3.connect(log)) as db:
        rows = [payload for (payload,) in db.execute("SELECT payload FROM decisions ORDER BY seq")]
    assert all(sample_id not in row and str(root) not in row and approval not in row for row in rows)
    assert [(e["action"], e["decision"], e["reason"]) for e in map(json.loads, rows)] == [
        ("evolution_erase", "pending", "replay_in_progress"),
        ("evolution_erase", "erased", None),
        ("evolution_erase", "confirmed", None),
    ]


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


def test_desktop_data_inventory_scopes_consents_and_tracks_pending_erasure(prepared_project, tmp_path):
    root, proposal, registry, approval = prepared_project
    other_root = tmp_path / "other"
    other_root.mkdir()
    data = ProjectData(root, registry)
    other = ProjectData(other_root, registry)
    assert data.inventory() == {"consents": [], "copies": [], "erasures": []}
    with pytest.raises(ProjectError, match="hors du projet"):
        ProjectData(root, root / "evolution.db")
    consent_id = data.grant(["source_code", "diffs"])["consent_id"]
    other_id = other.grant(["source_code"])["consent_id"]
    with pytest.raises(PlanningError, match="autre projet"):
        data.revoke(other_id)
    assert [row["consent_id"] for row in data.inventory()["consents"]] == [consent_id]
    assert [row["consent_id"] for row in other.inventory()["consents"]] == [other_id]

    samples = [collect(root, proposal, registry, category, consent_id, approval) for category in ("source_code", "diffs")]
    source, diff = samples
    output = tmp_path / "replayed"
    project.reuse(root, registry, diff["sample_id"], "diffs", output, tmp_path)
    report = output / "report.json"
    original_report = report.read_bytes()
    assert other.inventory()["copies"] == []
    data.revoke(consent_id)
    assert {row["status"] for row in data.inventory()["copies"]} == {"consent_revoked"}

    report.write_bytes(b"synthetic replacement")
    pending = data.erase(source["sample_id"])
    state = data.inventory()
    [erasure] = state["erasures"]
    assert erasure["request_id"] == pending["request_id"]
    assert (erasure["status"], erasure["reason"], erasure["count"]) == ("pending", "copy_unreachable", 2)
    assert {row["status"] for row in state["copies"]} == {"content_erasure_requested"}
    assert other.inventory()["erasures"] == []

    report.write_bytes(original_report)
    result = data.erase(erasure["sample_id"])
    assert result["copies_erased"] == 2 and result["reports_removed"] == 1
    state = data.inventory()
    assert state["copies"] == [] and state["erasures"][0]["status"] == "erased"
    assert not report.exists() and (root / "app.py").read_bytes() == b"value = 1\n"


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


def test_expiration_erases_the_copy_and_its_replay_at_the_deadline(prepared_project, tmp_path):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["diffs"])["consent_id"]
    sample = collect(root, proposal, registry, "diffs", consent, approval)
    output = tmp_path / "replayed"
    project.reuse(root, registry, sample["sample_id"], "diffs", output, tmp_path)
    expires = datetime.fromisoformat(sample["expires_at"])
    assert expire_copies(root, registry, now=expires - timedelta(microseconds=1)) == []
    assert (output / "report.json").is_file()
    result, = expire_copies(root, registry, now=expires)
    assert result["status"] == "erased" and result["reports_removed"] == 1
    assert (root / "app.py").read_bytes() == b"value = 1\n"
    assert not (output / "report.json").exists()
    assert expire_copies(root, registry, now=expires) == []
    with pytest.raises(ProjectError) as error:
        project.reuse(root, registry, sample["sample_id"], "diffs", tmp_path / "blocked", tmp_path)
    assert error.value.error.details["reason"] == "content_erasure_requested"


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


@pytest.mark.skipif(sys.platform != "win32", reason="Le coffre utilise DPAPI Windows.")
def test_restore_filters_the_source_deadline_before_the_archive_expires(prepared_project, tmp_path, monkeypatch):
    root, proposal, registry, approval = prepared_project
    consent = grant(registry, project_scope(root), ["diffs"])["consent_id"]
    sample = collect(root, proposal, registry, "diffs", consent, approval)
    archive_consent = grant_backup(root, registry, ["diffs"])["consent_id"]
    moment = datetime.now(timezone.utc)
    expiration = moment + timedelta(hours=1)
    created = expiration - timedelta(days=30)
    contents = content_path(root, registry)
    with closing(sqlite3.connect(contents)) as db, db:
        db.execute("UPDATE samples SET created_at = ?, expires_at = ? WHERE sample_id = ?",
                   (created.isoformat(), expiration.isoformat(), sample["sample_id"]))
    archive = tmp_path / "deadline.backup"
    result = backup(root, registry, archive, archive_consent)
    assert datetime.fromisoformat(result["expires_at"]) > expiration
    with closing(sqlite3.connect(contents)) as db, db:
        db.execute("DELETE FROM samples WHERE sample_id = ?", (sample["sample_id"],))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return expiration

    monkeypatch.setattr(backup_module, "datetime", Clock)
    restored = restore(root, registry, archive)
    assert restored["copies_restored"] == 0 and restored["skipped_inactive"] == 1
    with closing(sqlite3.connect(contents)) as db:
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone() == (0,)


@pytest.mark.skipif(sys.platform != "win32", reason="La sauvegarde quotidienne utilise DPAPI Windows.")
def test_daily_backup_recovers_publication_and_rotates_at_seven_days(prepared_project, tmp_path, monkeypatch):
    root, proposal, registry, approval = prepared_project
    evolution = grant(registry, project_scope(root), ["diffs"])["consent_id"]
    collect(root, proposal, registry, "diffs", evolution, approval)
    consent = grant_backup(root, registry, ["diffs"])["consent_id"]
    archives = tmp_path / "archives"
    with pytest.raises(ProjectError) as before_consent:
        daily_backup.run_daily(root, registry, archives, evolution)
    assert before_consent.value.error.details["reason"] == "backup_consent_missing"
    assert not archives.exists()
    start = datetime.now(timezone.utc)
    clock = [start]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(daily_backup, "datetime", Clock)
    monkeypatch.setattr(backup_module, "datetime", Clock)
    publish = backup_module.publish

    def interrupted(path, envelope):
        raise OSError("publication interrompue")

    monkeypatch.setattr(backup_module, "publish", interrupted)
    with pytest.raises(OSError, match="publication interrompue"):
        daily_backup.run_daily(root, registry, archives, consent)
    assert not list(archives.rglob("*.backup"))
    monkeypatch.setattr(backup_module, "publish", publish)
    first = daily_backup.run_daily(root, registry, archives, consent)
    archive = Path(first["archive"])
    assert first["status"] == "backed_up" and archive.is_file()
    same_day = daily_backup.run_daily(root, registry, archives, consent)
    assert same_day["status"] == "already_backed_up" and same_day["backup_id"] == first["backup_id"]

    clock[0] = start + timedelta(days=7, microseconds=-1)
    recent = daily_backup.run_daily(root, registry, archives, consent)
    assert not recent["rotated"] and archive.is_file()
    assert restore(root, registry, archive)["status"] == "restored"
    clock[0] = start + timedelta(days=7)
    after = daily_backup.run_daily(root, registry, archives, consent)
    assert after["rotated"] == [start.date().isoformat()] and after["pending_rotation"] == []
    assert not archive.exists() and Path(recent["archive"]).is_file()
    with closing(sqlite3.connect(vault_path(root, registry))) as db:
        assert db.execute("SELECT COUNT(*) FROM backup_keys WHERE backup_id = ?", (first["backup_id"],)).fetchone() == (0,)
    sample_id = ProjectData(root, registry).inventory()["copies"][0]["sample_id"]
    assert erase(root, registry, sample_id)["status"] == "erased"
    recovered = restore(root, registry, Path(recent["archive"]))
    assert recovered["copies_restored"] == 0 and recovered["skipped_erased"] == 1
    assert (root / "app.py").read_bytes() == b"value = 1\n"
