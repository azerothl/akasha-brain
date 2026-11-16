"""Exerce la garde de suppression et l'application réelle sur un projet jetable invité."""

import argparse
from contextlib import contextmanager, nullcontext
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from akasha_brain import project, project_approval, project_audit, project_transition

TARGET = "old.txt"
COMPANION = "companion.txt"
PAYLOAD = b"approved fixture\n"
PACKET = 0x4A000000

# code, raison, garde, risque. Le premier résultat est le témoin autorisé.
OUTCOMES = (
    ("applied", None, None, None),
    ("approval_required", None, None, "R2"),
    ("approval_required", None, None, "R3"),
    ("approval_expired", None, None, None),
    ("contract_precondition_failed", "project_changed", None, None),
    ("contract_precondition_failed", "project_changed", "transition", "R3"),
    ("contract_precondition_failed", "transition_unverifiable", "transition", "R3"),
)
CASES = {
    "missing_proposal_approval": (1, 0),
    "changed_proposal_after_approval": (1, 0),
    "missing_delete_approval": (2, 0),
    "wrong_delete_path": (2, 0),
    "expired_approval": (3, 0),
    "changed_target": (4, 0),
    "changed_companion": (4, 0),
    "same_bytes_and_mtime_new_file": (5, 1),
    "changed_target_after_checkpoint": (5, 1),
    "changed_companion_after_checkpoint": (4, 1),
    "changed_proposal_after_checkpoint": (2, 1),
    "locked_target": (6, 1),
    "approved_unchanged": (0, 1),
}
FLAGS = ("project_matches_expected", "checkpoint_matches_expected", "expected_native_handle_attempts",
         "expected_native_delete_calls", "audit_verified", "proposal_test_passed")


def snapshot(root: Path) -> dict:
    result = {}
    for path in sorted(root.iterdir()):
        info = path.stat()
        result[path.name] = (path.read_bytes(), info.st_ino, info.st_mtime_ns)
    return result


def validate_copy_in_guest(stage: Path, runtime: Path) -> dict:
    """Valide un second exemplaire dans le bac en cours, sans démarrer un bac imbriqué."""
    request = json.loads((stage / "validation.json").read_bytes())
    if request["operation"] != "delete" or request["absent"] != [TARGET] or request["dependencies"]:
        raise RuntimeError("Proposition de test inattendue.")
    work = stage / "work"
    shutil.copytree(stage / "snapshot", work)
    (work / TARGET).unlink()
    subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(work / request["test"])],
                   cwd=work, check=True, timeout=10)
    hashes = {path.name: project.digest(path.read_bytes()) for path in work.iterdir() if path.is_file()}
    if hashes != request["files"]:
        raise RuntimeError("Le test de la copie invitée a modifié son état attendu.")
    return {"status": "passed", "guest_exit_code": 0x4700}


def run_case(case: str, directory: Path) -> int:
    expected_outcome, expected_handles = CASES[case]
    root = directory / "project"
    root.mkdir()
    target, companion = root / TARGET, root / COMPANION
    target.write_bytes(PAYLOAD)
    companion.write_bytes(b"companion\n")
    (root / "check.py").write_bytes(
        b"from pathlib import Path\nassert not Path('old.txt').exists()\n"
        b"assert Path('companion.txt').read_bytes() == b'companion\\n'\n"
    )
    proposal = directory / "proposal"
    with patch.object(project, "validate_in_sandbox", validate_copy_in_guest):
        prepared = project.prepare(root, proposal, TARGET, None, "check.py", Path(sys.prefix),
                                   inputs=(COMPANION,), delete=True)
    manifest_path = proposal / "proposal.json"
    approved = prepared["approval_sha256"]
    approved_delete = TARGET

    if case == "missing_proposal_approval":
        approved = None
    elif case == "changed_proposal_after_approval":
        manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    elif case == "missing_delete_approval":
        approved_delete = None
    elif case == "wrong_delete_path":
        approved_delete = COMPANION
    elif case == "expired_approval":
        manifest = json.loads(manifest_path.read_bytes())
        deadline = project_approval.utc_now() - timedelta(minutes=1)
        manifest["approval"]["issued_at"] = (deadline - timedelta(minutes=30)).isoformat()
        manifest["approval"]["expires_at"] = deadline.isoformat()
        encoded = json.dumps(manifest).encode("utf-8")
        manifest_path.write_bytes(encoded)
        approved = project.digest(encoded)
    elif case == "changed_target":
        target.write_bytes(b"edited after approval\n")
    elif case == "changed_companion":
        companion.write_bytes(b"edited companion\n")
    elif case == "same_bytes_and_mtime_new_file":
        previous = target.stat()
        target.rename(root / "reviewed.txt")
        target.write_bytes(PAYLOAD)
        os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        assert target.stat().st_ino != previous.st_ino
        assert target.stat().st_mtime_ns == previous.st_mtime_ns
        assert project.check_current(root, json.loads(manifest_path.read_bytes()))[TARGET] == PAYLOAD

    manifest = json.loads(manifest_path.read_bytes())
    key = project_approval.action_key(manifest)
    expected = snapshot(root)
    if expected_outcome == 0:
        del expected[TARGET]
    original_mark = project.mark_application
    original_handle = project_transition.deletion_handle
    handle_calls = delete_calls = 0

    def mark_with_interleaving(path, action, state):
        nonlocal expected
        original_mark(path, action, state)
        if state == "applying":
            if case == "changed_target_after_checkpoint":
                target.write_bytes(b"edited after checkpoint\n")
                expected = snapshot(root)
            elif case == "changed_companion_after_checkpoint":
                companion.write_bytes(b"companion edited after checkpoint\n")
                expected = snapshot(root)
            elif case == "changed_proposal_after_checkpoint":
                manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

    @contextmanager
    def trace_handle(path):
        nonlocal handle_calls, delete_calls
        handle_calls += 1
        with original_handle(path) as (stream, remove):
            def traced_remove():
                nonlocal delete_calls
                delete_calls += 1
                remove()

            yield stream, traced_remove

    lock = target.open("rb") if case == "locked_target" else nullcontext()
    with lock, patch.object(project, "mark_application", mark_with_interleaving), \
            patch.object(project_transition, "deletion_handle", trace_handle):
        try:
            outcome = (project.apply(root, proposal, approved, approved_delete=approved_delete)["status"],
                       None, None, None)
        except project.ProjectError as error:
            details = error.error.details
            outcome = (error.error.code.value, details.get("reason"), details.get("guard"), details.get("risk_class"))

    audit = project_audit.verify(directory / project_audit.LOG_NAME)
    checks = (
        snapshot(root) == expected,
        project_approval.application_state(proposal, key) == ("applied" if expected_outcome == 0 else None),
        handle_calls == expected_handles,
        delete_calls == int(expected_outcome == 0),
        audit == {"status": "passed", "entries_verified": 1 + int(expected_handles and expected_outcome != 0)},
        prepared["validation"]["guest_exit_code"] == 0x4700,
    )
    outcome_id = OUTCOMES.index(outcome) if outcome in OUTCOMES else 0xFF
    return PACKET | (outcome_id << 8) | sum(passed << bit for bit, passed in enumerate(checks))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=tuple(CASES))
    args = parser.parse_args()
    with TemporaryDirectory(prefix="AkashaTransition-") as work:
        code = run_case(args.case, Path(work).resolve(strict=True))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
