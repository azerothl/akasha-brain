import json
from pathlib import Path
import sys

import pytest

from akasha_brain import project
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


@pytest.mark.parametrize("name", ["../other.py", "dir\\..\\other.py", "C:outside.py", ".git/config", "AUX"])
def test_rejects_paths_outside_the_editable_scope(tmp_path: Path, name):
    with pytest.raises(project.ProjectError) as error:
        project.project_file(tmp_path, name)
    assert error.value.error.code == ErrorCode.PERMISSION_DENIED


@pytest.mark.skipif(sys.platform != "win32", reason="Le parcours cible Windows Sandbox.")
def test_applies_an_existing_version_one_proposal(prepared):
    root, output, _ = prepared
    path = output / "proposal.json"
    manifest = json.loads(path.read_bytes())
    manifest["version"] = 1
    manifest.pop("operation")
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
    approval = {"approved_delete": source} if operation == "delete" else {"approved_move": (source, destination)}
    assert project.apply(root, output, receipt, **approval)["operation"] == operation
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
