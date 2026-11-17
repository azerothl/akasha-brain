"""État versionné et prédiction symbolique d'un remplacement de fichier."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import subprocess

from .project import project_file, project_input

VERSION = "1.0.0"
MAX_FILES = 32
MAX_BYTES = 256 * 1024


def git(project: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(project), "--no-optional-locks", "--literal-pathspecs", *args],
                          check=True, capture_output=True, timeout=15,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


def file_state(content: bytes) -> dict:
    return {"sha256": sha256(content).hexdigest(), "size_bytes": len(content)}


def capture(project: Path, names: tuple[str, ...]) -> dict:
    project = project.resolve(strict=True)
    if not 1 <= len(names) <= MAX_FILES or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Le périmètre CodeState doit contenir des fichiers distincts.")
    top = Path(git(project, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if top != project:
        raise ValueError("CodeState exige la racine du dépôt Git.")
    files = {name: file_state(project_input(project_file(project, name), byte_limit=MAX_BYTES)) for name in names}
    status = git(project, "status", "--porcelain=v1", "-z", "--no-renames", "--", *names).decode("utf-8")
    return {
        "type": "CodeState", "version": VERSION, "observed_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {"files": "host_file_bytes", "git": "local_git"},
        "files": files,
        "git": {"head": git(project, "rev-parse", "HEAD").decode("ascii").strip(),
                "index_scope_sha256": sha256(git(project, "ls-files", "--stage", "-z", "--", *names)).hexdigest(),
                "worktree_status": status.rstrip("\x00").split("\x00") if status else []},
    }


def predict_replacement(state: dict, target: str, expected_sha256: str, replacement: bytes, *, approved: bool) -> dict:
    if state.get("type") != "CodeState" or state.get("version") != VERSION or target not in state["files"]:
        raise ValueError("L'action doit porter sur un fichier observé par CodeState v1.")
    if not approved:
        outcome = "approval_required"
    elif state["files"][target]["sha256"] != expected_sha256:
        outcome = "project_changed"
    else:
        outcome = "applied"
    expected = {name: dict(values) for name, values in state["files"].items()}
    if outcome == "applied":
        expected[target] = file_state(replacement)
    return {
        "version": VERSION, "from_observed_at": state["observed_at"],
        "action": {"kind": "replace", "file": target, "expected_sha256": expected_sha256, "approved": approved},
        "outcome": outcome, "files": expected,
        "git": {name: state["git"][name] for name in ("head", "index_scope_sha256")},
    }


def compare(prediction: dict, observed: dict, outcome: str) -> dict:
    if (observed.get("type") != "CodeState" or observed.get("version") != prediction["version"]
            or set(prediction["files"]) != set(observed["files"])):
        raise ValueError("L'observation doit reprendre le périmètre CodeState de la prévision.")
    variables = {"outcome": {"predicted": prediction["outcome"], "observed": outcome}}
    for name, fields in prediction["files"].items():
        for key, value in fields.items():
            variables[f"files/{name}/{key}"] = {"predicted": value, "observed": observed["files"][name][key]}
    for key, value in prediction["git"].items():
        variables[f"git/{key}"] = {"predicted": value, "observed": observed["git"][key]}
    mismatches = [name for name, values in variables.items() if values["predicted"] != values["observed"]]
    return {"status": "passed" if not mismatches else "failed", "variables": variables, "mismatches": mismatches}
