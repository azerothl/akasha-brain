"""Premier relevé Phase 5 sur un remplacement de code dans un projet jetable."""

import argparse
import json
from pathlib import Path

from akasha_brain import code_state
from akasha_brain.project import apply, prepare
from akasha_brain.project_common import ProjectError
from bench.run_guided_repair import BENCH, file_hash, write_report

PRIOR = BENCH / "results/project-delete-transition-v1.json"
TARGET = "value.py"
FILES = (TARGET, "check.py", "companion.txt")


def run(runtime: Path, output: Path) -> dict:
    prior = json.loads(PRIOR.read_bytes())
    if prior["status"] != "passed" or not all(case["file_preserved"] for case in prior["cases"].values()):
        raise RuntimeError("La preuve de transition Phase 3 est incomplète.")
    output.mkdir(parents=True)
    project = output / "disposable-project"
    project.mkdir()
    source = project / TARGET
    source.write_bytes(b"VALUE = 1\n")
    (project / "check.py").write_bytes(b"from value import VALUE\nassert VALUE == 42\n")
    (project / "companion.txt").write_bytes(b"companion file\n")
    replacement = output / "replacement.py"
    replacement.write_bytes(b"VALUE = 42\n")
    code_state.git(project, "init", "--quiet")
    code_state.git(project, "config", "--local", "core.autocrlf", "false")
    code_state.git(project, "add", "--", *FILES)
    code_state.git(project, "-c", "user.name=Akasha Bench", "-c", "user.email=bench@example.invalid",
                   "commit", "--quiet", "-m", "Initialiser le projet jetable")
    observed = code_state.capture(project, FILES)
    if observed["git"]["worktree_status"]:
        raise RuntimeError("Le projet jetable doit partir d'un arbre de travail propre.")
    proposal = output / "proposal"
    prepared = prepare(project, proposal, TARGET, replacement, "check.py", runtime, inputs=["companion.txt"])
    validation = prepared["validation"]
    if (prepared["status"] != "awaiting_approval" or validation["status"] != "passed"
            or validation["guest_exit_code"] != 0x4700 or not validation["sandbox_stopped"]
            or not validation["read_only_input"]):
        raise RuntimeError("La proposition doit avoir réussi ses tests dans Windows Sandbox.")
    after_prepare = code_state.capture(project, FILES)
    if any(observed[key] != after_prepare[key] for key in ("files", "git")):
        raise RuntimeError("La validation isolée a changé le projet.")
    approval = prepared["approval_sha256"]
    expected_source = observed["files"][TARGET]["sha256"]
    result = {"status": "running", "protocol": "phase5-code-transition-v1", "scope": "disposable",
              "prior_phase3_sha256": file_hash(PRIOR), "sandbox_validation": validation,
              "preparation_preserved_project": True, "runs": {}}
    write_report(output, result)

    for name, approved, current_bytes in (
        ("approval_missing", False, b"VALUE = 1\n"),
        ("stale_source", True, b"VALUE = 23\n"),
        ("approved_replace", True, b"VALUE = 1\n"),
    ):
        if source.read_bytes() != current_bytes:
            source.write_bytes(current_bytes)
        before = code_state.capture(project, FILES)
        forecast = code_state.predict_replacement(before, TARGET, expected_source, replacement.read_bytes(),
                                                 approved=approved)
        # Persiste la prévision avant l'appel du parcours projet.
        run = {"before": before, "prediction": forecast}
        result["runs"][name] = run
        write_report(output, result)
        try:
            applied = apply(project, proposal, approval if approved else None)
            outcome = applied["status"]
        except ProjectError as error:
            outcome = error.error.details.get("reason", error.error.code.value)
        after = code_state.capture(project, FILES)
        checks = code_state.compare(forecast, after, outcome)
        run.update(observed=after, observed_outcome=outcome, comparison=checks)
        write_report(output, result)
        print(name, outcome, len(checks["variables"]), "variables", flush=True)
        if checks["status"] != "passed":
            raise RuntimeError(f"Les états prévu et observé divergent pour {name}.")
    result["status"] = "passed"
    result["matched_variables"] = sum(len(run["comparison"]["variables"]) for run in result["runs"].values())
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.runtime.resolve(strict=True), args.output.resolve())
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
