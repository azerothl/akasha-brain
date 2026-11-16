import json
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys

import pytest

from akasha_brain import project, project_approval, project_audit
from contracts.akasha_contracts.errors import ErrorCode


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / "code"
    root.mkdir()
    (root / "app.py").write_bytes(b"value = 1\n")
    (root / "check.py").write_bytes(b"from app import value\nassert value == 2\n")
    (root / "settings.ini").write_bytes(b"mode=default\n")
    replacement = tmp_path / "replacement.py"
    replacement.write_bytes(b"value = 2\n")
    output = tmp_path / "proposal"

    def validate(stage, runtime):
        assert (stage / "snapshot/app.py").read_bytes() == b"value = 1\n"
        assert (stage / "snapshot/check.py").read_bytes() == (root / "check.py").read_bytes()
        assert b"+value = 2\n" in (stage / "proposal.diff").read_bytes()
        return {"status": "passed", "guest_exit_code": 0x4700}

    monkeypatch.setattr(project, "validate_in_sandbox", validate)
    result = project.prepare(root, output, "app.py", replacement, "check.py", tmp_path, inputs=["settings.ini"])
    return root, output, result["approval_sha256"]


@pytest.mark.parametrize("approval", [None, "different-proposal"])
def test_rejects_missing_or_different_approval(prepared, approval):
    root, output, _ = prepared
    with pytest.raises(project.ProjectError) as error:
        project.apply(root, output, approval)
    assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
    assert (root / "app.py").read_bytes() == b"value = 1\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_applies_exactly_the_approved_change(prepared):
    root, output, approval = prepared
    assert project.apply(root, output, approval)["status"] == "applied"
    assert (root / "app.py").read_bytes() == b"value = 2\n"
    assert (root / "settings.ini").read_bytes() == b"mode=default\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_approval_audit_is_chained_and_contains_only_decision_metadata(prepared):
    root, output, approval = prepared
    with pytest.raises(project.ProjectError):
        project.apply(root, output)
    assert project.apply(root, output, approval)["status"] == "applied"
    log = output.parent / project_audit.LOG_NAME
    assert project_audit.verify(log) == {"status": "passed", "entries_verified": 2}
    with sqlite3.connect(log) as db:
        events = [json.loads(raw) for (raw,) in db.execute("SELECT payload FROM decisions ORDER BY seq")]
        assert [(e["decision"], e["actor"], e["risk_class"]) for e in events] == [
            ("refused", "runtime", "R2"), ("approved", "human", "R2"),
        ]
        assert all(set(e) == {"created_at", "actor", "risk_class", "action", "decision", "reason",
                              "policy_version", "capability_version", "previous"} for e in events)
        assert all(field not in json.dumps(events) for field in ("app.py", "value =", approval, str(root)))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM decisions")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE decisions SET digest = 'changed'")
        db.execute("DROP TRIGGER no_edit_decisions")
        db.execute("UPDATE decisions SET digest = 'damaged' WHERE seq = 2")
    assert project_audit.verify(log) == {"status": "failed", "entries_verified": 1, "invalid_entry": 2}


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
@pytest.mark.parametrize("expires_during_checkpoint", [False, True])
def test_expired_approval_requires_a_fresh_review(prepared, monkeypatch, expires_during_checkpoint):
    root, output, approval = prepared
    old = project.preview_proposal(root, output)
    clock = [old.approval_expires_at]
    monkeypatch.setattr(project_approval, "utc_now", lambda: clock[0])
    normal_checkpoint = project.mark_application
    if expires_during_checkpoint:
        clock[0] -= timedelta(microseconds=1)

        def mark(*args):
            normal_checkpoint(*args)
            clock[0] = old.approval_expires_at

        monkeypatch.setattr(project, "mark_application", mark)
    with pytest.raises(project.ProjectError) as error:
        old.apply(True)
    assert error.value.error.code == ErrorCode.APPROVAL_EXPIRED
    assert (root / "app.py").read_bytes() == b"value = 1\n"
    monkeypatch.setattr(project, "mark_application", normal_checkpoint)

    request = project.renew_approval(root, output)
    fresh = project.preview_proposal(root, output)
    assert fresh.approval_sha256 == request["approval_sha256"] != approval
    assert fresh.approval_expires_at > old.approval_expires_at
    with pytest.raises(project.ProjectError) as error:
        old.apply(True)
    assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
    with pytest.raises(project.ProjectError) as error:
        fresh.apply(False)
    assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
    assert fresh.apply(True)["status"] == "applied"


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_durable_checkpoint_prevents_applying_again_after_interruption(prepared, monkeypatch):
    root, output, approval = prepared
    normal = project.mark_application

    def interrupt(proposal, key, state):
        if state == "applied":
            raise OSError("Interrupted after the file effect")
        normal(proposal, key, state)

    monkeypatch.setattr(project, "mark_application", interrupt)
    with pytest.raises(OSError, match="Interrupted"):
        project.apply(root, output, approval)
    assert (root / "app.py").read_bytes() == b"value = 2\n"

    monkeypatch.setattr(project, "mark_application", normal)
    monkeypatch.setattr(project, "apply_replacement", lambda *args: pytest.fail("Le diff a été appliqué deux fois."))
    recovered = project.apply(root, output, approval)
    assert recovered["replayed"] and recovered["recovered"]
    assert not project.apply(root, output, approval)["recovered"]
    (root / "app.py").write_bytes(b"value = 1\n")
    with pytest.raises(project.ProjectError) as error:
        project.apply(root, output, approval)
    assert error.value.error.details["reason"] == "project_changed_after_apply"
    assert (root / "app.py").read_bytes() == b"value = 1\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
@pytest.mark.parametrize("changed", ["app.py", "settings.ini"])
def test_refuses_stale_proposal_even_with_approval(prepared, changed):
    root, output, approval = prepared
    earlier = (root / "app.py").read_bytes()
    (root / changed).write_bytes(b"concurrent = True\n")
    with pytest.raises(project.ProjectError) as error:
        project.apply(root, output, approval)
    assert error.value.error.code == ErrorCode.CONTRACT_PRECONDITION_FAILED
    assert error.value.error.details["reason"] == "project_changed"
    assert (root / changed).read_bytes() == b"concurrent = True\n"
    if changed != "app.py":
        assert (root / "app.py").read_bytes() == earlier


def test_refuses_modified_diff_after_review(prepared):
    root, output, approval = prepared
    (output / "proposal.diff").write_bytes(b"modified patch")
    with pytest.raises(project.ProjectError) as error:
        project.apply(root, output, approval)
    assert error.value.error.details["reason"] == "proposal_changed"
    assert (root / "app.py").read_bytes() == b"value = 1\n"


def test_preview_binds_the_displayed_diff_to_the_reviewed_manifest(prepared):
    root, proposal, approval = prepared
    review = project.preview_replacement(root, proposal)
    assert review.diff.encode("utf-8") == (proposal / "proposal.diff").read_bytes()
    assert review.approval_sha256 == approval
    with pytest.raises(project.ProjectError) as error:
        review.apply(False)
    assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
    manifest = proposal / "proposal.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(project.ProjectError) as error:
        review.apply(True)
    assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
    assert (root / "app.py").read_bytes() == b"value = 1\n"


def test_preview_rejects_a_diff_whose_bytes_do_not_match_the_manifest(prepared):
    root, proposal, _ = prepared
    (proposal / "proposal.diff").write_bytes(b"replacement diff")
    with pytest.raises(project.ProjectError) as error:
        project.preview_replacement(root, proposal)
    assert error.value.error.details["reason"] == "proposal_changed"


@pytest.mark.parametrize("name", ["../other.py", "dir\\..\\other.py", "C:outside.py", ".git/config", "AUX"])
def test_rejects_paths_outside_the_editable_scope(tmp_path: Path, name):
    with pytest.raises(project.ProjectError) as error:
        project.project_file(tmp_path, name)
    assert error.value.error.code == ErrorCode.PERMISSION_DENIED


@pytest.mark.parametrize("name", [".env", "nested/.ENV.local", "keys/service.pfx", ".ssh/config"])
def test_rejects_secret_inputs_before_staging(tmp_path, name):
    with pytest.raises(project.ProjectError) as error:
        project.project_file(tmp_path, name)
    assert error.value.error.details["reason"] == "secret_input"


def test_rejects_a_private_key_embedded_in_an_explicit_input(tmp_path):
    source = tmp_path / "ordinary.py"
    source.write_bytes(b'key = "-----BEGIN OPENSSH PRIVATE KEY-----"\n')
    with pytest.raises(project.ProjectError) as error:
        project.snapshot(tmp_path, [source.name])
    assert error.value.error.details["reason"] == "secret_input"


def test_inspect_code_bounds_reads_and_searches_only_selected_files(tmp_path):
    (tmp_path / "a.py").write_text("first\n" + "x" * 600 + " À FAIRE\nlast\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("à faire\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("à faire\n", encoding="utf-8")
    view = project.inspect_code(tmp_path, ["a.py"], first_line=2, limit=1)
    assert [(row["line"], len(row["text"])) for row in view["lines"]] == [(2, 500)]
    assert view["more"] and view["lines"][0]["excerpt"]
    found = project.inspect_code(tmp_path, ["a.py", "b.py"], contains="à faire")
    assert [(row["file"], row["line"]) for row in found["lines"]] == [("a.py", 2), ("b.py", 1)]
    assert "À FAIRE" in found["lines"][0]["text"]
    (tmp_path / "large.txt").write_bytes(b"x" * (project.CODE_FILE_LIMIT + 1))
    with pytest.raises(project.ProjectError) as error:
        project.inspect_code(tmp_path, ["large.txt"])
    assert error.value.error.code == ErrorCode.RESOURCE_BUDGET_EXCEEDED


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_applies_an_existing_version_one_proposal(prepared):
    root, output, _ = prepared
    path = output / "proposal.json"
    manifest = json.loads(path.read_bytes())
    manifest["version"] = 1
    manifest.pop("operation")
    manifest.pop("approval")
    encoded = json.dumps(manifest).encode("utf-8")
    path.write_bytes(encoded)
    assert project.apply(root, output, project.digest(encoded))["status"] == "applied"
    assert (root / "app.py").read_bytes() == b"value = 2\n"


@pytest.fixture(params=["delete", "move"])
def file_operation(tmp_path, monkeypatch, request):
    operation = request.param
    root = tmp_path / "code"
    root.mkdir()
    payload = b"\x00\xff\x01"
    source = "old.bin"
    destination = "archive/notes café.bin"
    (root / "archive").mkdir()
    (root / source).write_bytes(payload)
    (root / "check.py").write_bytes(b"assert True\n")
    output = tmp_path / "proposal"

    def validate(stage, runtime):
        checks = json.loads((stage / "validation.json").read_bytes())
        assert checks["operation"] == operation
        assert checks["absent"] == [source]
        assert (stage / "snapshot" / source).read_bytes() == payload
        if operation == "move":
            assert checks["files"][destination] == project.digest(payload)
        return {"status": "passed", "guest_exit_code": 0x4700}

    monkeypatch.setattr(project, "validate_in_sandbox", validate)
    options = {"delete": True} if operation == "delete" else {"move_to": destination}
    prepared = project.prepare(root, output, source, None, "check.py", tmp_path, **options)
    return root, output, prepared["approval_sha256"], operation, source, destination, payload


def test_requires_the_matching_operation_approval(file_operation):
    root, output, receipt, operation, source, destination, payload = file_operation
    wrong_kind = {"approved_move": (source, destination)} if operation == "delete" else {"approved_delete": source}
    wrong_path = {"approved_delete": "other.bin"} if operation == "delete" else {"approved_move": (source, "other.bin")}
    for approval in ({}, wrong_kind, wrong_path):
        with pytest.raises(project.ProjectError) as error:
            project.apply(root, output, receipt, **approval)
        assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
        assert error.value.error.details["operation"] == operation
        assert (root / source).read_bytes() == payload
        assert not (root / destination).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_applies_the_specifically_approved_operation(file_operation):
    root, output, receipt, operation, source, destination, payload = file_operation
    review = project.preview_proposal(root, output)
    assert review.approval_sha256 == receipt
    assert review.diff is None and review.operation == operation and review.target == source
    assert review.destination == (destination if operation == "move" else None)

    for proposal_ok, operation_ok, risk in ((False, False, "R2"), (False, True, "R2"), (True, False, "R3")):
        with pytest.raises(project.ProjectError) as error:
            review.apply(proposal_ok, approved_operation=operation_ok)
        assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
        assert error.value.error.details["risk_class"] == risk
        assert (root / source).read_bytes() == payload
        assert not (root / destination).exists()

    assert review.apply(True, approved_operation=True)["operation"] == operation
    assert not (root / source).exists()
    if operation == "move":
        assert (root / destination).read_bytes() == payload
    assert (root / "check.py").read_bytes() == b"assert True\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_stale_operation_preserves_the_source_and_any_existing_destination(file_operation):
    root, output, receipt, operation, source, destination, payload = file_operation
    if operation == "delete":
        (root / source).write_bytes(b"source changed")
        approval = {"approved_delete": source}
    else:
        (root / destination).write_bytes(b"destination created")
        approval = {"approved_move": (source, destination)}
    with pytest.raises(project.ProjectError) as error:
        project.apply(root, output, receipt, **approval)
    assert error.value.error.details["reason"] == "project_changed"
    if operation == "delete":
        assert (root / source).read_bytes() == b"source changed"
    else:
        assert (root / source).read_bytes() == payload
        assert (root / destination).read_bytes() == b"destination created"
