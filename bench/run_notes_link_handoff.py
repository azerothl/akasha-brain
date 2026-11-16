"""Évalue le lien Notes figé avec des remises invalides dans des bacs neufs."""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from unittest.mock import patch

from akasha_brain import notes_runtime
from akasha_brain.notes_evolution import evidence
from akasha_brain.notes_link_candidate import ADAPTER_STEP, INPUT_NAME, PATCH_CHECKS
from akasha_brain.notes_repair import RbitnetPaths
from bench.run_guided_repair import CHECKPOINTS, execution_limits, file_hash, write_report
from bench.run_notes_link_comparison import CPU_THREADS, MODEL_RAM_MIB, ROOT, compile_graphs, require_freeze

CASES_FILE = Path(__file__).with_name("notes-link-handoff-reserved-v1.json")
LOCK_FILE = ROOT / "akasha_brain" / "protocols" / "notes-link-adapter-v1.json"
DESKTOP_FILE = ROOT / "akasha_brain" / "protocols" / "notes-desktop-ocr-v2.json"
CASES = {
    "missing_digest": "diff_sha256",
    "wrong_attempt": "diff_file",
    "staged_diff_changed": "staged_diff_sha256",
    "valid_control": None,
}


def perturb(case: str, receipt: dict, staged: Path, expected: str) -> dict:
    if (not all(receipt.get(key) is True for key in PATCH_CHECKS)
            or receipt.get("guest_apply_exit") != 0x4602 or receipt.get("matches_desktop_protocol") is not True
            or receipt.get("diff_file") != f"{INPUT_NAME}/proposal.diff"
            or receipt.get("diff_sha256") != expected or staged.resolve() != staged or file_hash(staged) != expected):
        raise RuntimeError("La remise initiale doit être complète et le diff réellement appliqué.")
    if case == "missing_digest":
        receipt.pop("diff_sha256")
    elif case == "wrong_attempt":
        receipt["diff_file"] = "rbitnet-2/proposal.diff"
    elif case == "staged_diff_changed":
        staged.write_bytes(staged.read_bytes() + b"\n")
    return {"applied_digest": expected, "received_digest": receipt.get("diff_sha256"),
            "received_path": receipt["diff_file"], "staged_digest": file_hash(staged)}


def observe_validity(observation: dict) -> bool:
    return (observation["received_digest"] == observation["applied_digest"] == observation["staged_digest"]
            and observation["received_path"] == f"{INPUT_NAME}/proposal.diff")


@contextmanager
def instrument(case: str, output: Path, expected: str):
    """Injecte après le succès Git observé. Les appels invités passent au vrai exécuteur."""
    write = notes_runtime.write_report
    guest = notes_runtime.guest_exit
    observed = {"handoff": None, "verify_calls": 0}

    def report(directory, document):
        trace = document["trace"]
        if (observed["handoff"] is None and trace and document["status"] == "running"
                and trace[-1]["id"] == "generate_diff" and trace[-1]["status"] == "passed"):
            staged = output / "input" / INPUT_NAME / "proposal.diff"
            observed["handoff"] = perturb(case, trace[-1]["result"], staged, expected)
        write(directory, document)

    def guest_call(sandbox_id, command):
        if command.endswith(" -VerifyPrepared"):
            observed["verify_calls"] += 1
        return guest(sandbox_id, command)

    with patch.object(notes_runtime, "write_report", report), patch.object(notes_runtime, "guest_exit", guest_call):
        yield observed


def validate_cases(document: dict) -> None:
    rows = document["cases"]
    if (document["version"] != 1 or document["boundary"] != "after_guest_apply_before_verify"
            or len(rows) != len(CASES) or {row["id"] for row in rows} != set(CASES)):
        raise ValueError("Corpus de remises réservé invalide.")
    for row in rows:
        if (type(row["seed"]) is not int or row["seed"] < 0 or sorted(row["order"]) != ["candidate", "parent"]
                or row["valid"] is not (CASES[row["id"]] is None)):
            raise ValueError("Protocole d'un cas réservé invalide.")


def measure(report: dict, observed: dict, graph: dict, case: dict) -> dict:
    trace = {row["id"]: row for row in report["trace"]}
    handoff = observed["handoff"]
    valid = handoff is not None and observe_validity(handoff)
    error = report.get("error") or {}
    rejected = error.get("details", {}).get("invalid_checks", [])
    candidate = ADAPTER_STEP in {step["id"] for step in graph["steps"]}
    rejected_at_link = (error.get("code") == "contract_precondition_failed"
                        and trace.get(ADAPTER_STEP, {}).get("status") == "failed" and bool(rejected)
                        and observed["verify_calls"] == 0)
    verdict = "accepted" if observed["verify_calls"] else "rejected" if rejected_at_link else "undetermined"
    if case["valid"]:
        expected = evidence(report, desktop=True)["verified"] and observed["verify_calls"] == 1
    elif candidate:
        expected = rejected_at_link and rejected == [CASES[case["id"]]]
    else:
        expected = (observed["verify_calls"] == 1 and trace.get("verify", {}).get("status") == "passed"
                    and trace.get("verify_desktop", {}).get("status") == "passed")
        if case["id"] == "staged_diff_changed":
            expected = expected and report["status"] == "failed" and report["isolation"].get("host_staging_unchanged") is False
        else:
            expected = expected and report["status"] == "passed"
    repair = report.get("repair", {})
    evaluated = (handoff is not None and valid == case["valid"] and report["graph"] == graph
                 and bool(report.get("sandbox_id")) and report.get("sandbox_stopped") is True
                 and repair.get("backend") == "cpu" and repair.get("hashes") == CHECKPOINTS
                 and repair.get("seeds") == (case["seed"],) and verdict != "undetermined")
    step_times = {row["id"]: row["wall_s"] for row in report["trace"]}
    return {
        "evaluated": bool(evaluated), "expected_behavior": expected, "handoff_verdict": verdict,
        "sandbox_id": report.get("sandbox_id"), "handoff": handoff,
        "verify_calls": observed["verify_calls"],
        "false_handoff_acceptances": observed["verify_calls"] if handoff is not None and not valid else 0,
        "retries": sum(row["id"] == "generate_diff" and row.get("attempt", 1) > 1 for row in report["trace"]),
        "workflow_status": report["status"], "error": report.get("error"), "invalid_checks": rejected,
        "tests_passed": trace.get("verify", {}).get("result", {}).get("passed"),
        "sqlite_exit": trace.get("verify", {}).get("result", {}).get("sqlite_verifier_exit"),
        "desktop": trace.get("verify_desktop", {}).get("result", {}).get("desktop"),
        "steps_s": step_times, "total_s": report["wall_s"],
        "downstream_s": round(sum(step_times.get(step, 0) for step in ("verify", "verify_desktop")), 3),
    }


def run(runtime: Path, repair: RbitnetPaths, output: Path) -> dict:
    corpus = json.loads(CASES_FILE.read_bytes())
    validate_cases(corpus)
    frozen = json.loads(LOCK_FILE.read_bytes())
    goal, catalog, graphs = compile_graphs()
    require_freeze(frozen, graphs)
    lock_digest = sha256(LOCK_FILE.read_text(encoding="utf-8").encode()).hexdigest()
    if lock_digest != corpus["adapter_freeze_sha256"] or repair.backend != "cpu":
        raise RuntimeError("Le corpus exige l'adaptateur figé et Rbitnet CPU.")
    expected_digest = json.loads(DESKTOP_FILE.read_bytes())["diff_sha256"]
    case_digest = file_hash(CASES_FILE)
    harness_digest = file_hash(Path(__file__))
    output.mkdir(parents=True)
    result = {"status": "running", "freeze_sha256": lock_digest, "cases_sha256": case_digest,
              "harness_sha256": harness_digest,
              "cpu_threads": CPU_THREADS, "model_ram_mib": MODEL_RAM_MIB, "cases": []}
    write_report(output, result)
    for case in corpus["cases"]:
        pair = {**case, "runs": {}}
        result["cases"].append(pair)
        for arm in case["order"]:
            require_freeze(frozen, compile_graphs()[2])
            if file_hash(CASES_FILE) != case_digest:
                raise RuntimeError("Le corpus réservé a changé pendant l'essai.")
            folder = output / case["id"] / arm
            print(f"{case['id']} {arm} graine {case['seed']}", flush=True)
            with instrument(case["id"], folder, expected_digest) as observation:
                with execution_limits(None, cpu_threads=CPU_THREADS, model_ram_mb=MODEL_RAM_MIB):
                    report = notes_runtime.run_notes(goal, catalog, runtime, folder, repair, rapidocr=True,
                                                     first_diff_seed=case["seed"], origin="reserved_handoff",
                                                     link_candidate=arm == "candidate")
            measured = measure(report, observation, graphs[arm], case)
            pair["runs"][arm] = measured
            write_report(output, result)
            print(json.dumps({key: measured[key] for key in (
                "evaluated", "false_handoff_acceptances", "retries", "workflow_status", "total_s")}), flush=True)

    require_freeze(json.loads(LOCK_FILE.read_bytes()), compile_graphs()[2])
    if file_hash(CASES_FILE) != case_digest or file_hash(Path(__file__)) != harness_digest:
        raise RuntimeError("Le corpus ou le lanceur réservé a changé pendant la campagne.")
    evaluated = [case for case in result["cases"] if all(row["evaluated"] for row in case["runs"].values())]
    invalid = [case for case in evaluated if not case["valid"]]
    ids = {row["sandbox_id"] for case in result["cases"] for row in case["runs"].values() if row["sandbox_id"]}
    result.update(status="passed" if len(evaluated) == len(CASES) and len(ids) == 2 * len(CASES) else "failed",
                  evaluated_pairs=len(evaluated), invalid_pairs=len(invalid), distinct_sandboxes=len(ids))
    if invalid:
        result["invalid_summary"] = {
            arm: {"false_acceptances": sum(case["runs"][arm]["false_handoff_acceptances"] for case in invalid),
                  "retries": sum(case["runs"][arm]["retries"] for case in invalid),
                  "median_total_s": median(case["runs"][arm]["total_s"] for case in invalid),
                  "median_downstream_s": median(case["runs"][arm]["downstream_s"] for case in invalid)}
            for arm in ("parent", "candidate")
        }
        result["median_paired_total_delta_s"] = median(
            round(case["runs"]["candidate"]["total_s"] - case["runs"]["parent"]["total_s"], 3) for case in invalid)
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", type=Path, nargs=3, required=True, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repair = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet), model_ram_mib=MODEL_RAM_MIB)
    result = run(args.runtime.resolve(strict=True), repair, args.output.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
