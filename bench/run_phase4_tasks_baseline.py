"""Caractérise la référence Tâches sur deux cas de développement synthétiques."""

import argparse
import json
from pathlib import Path
import shutil

from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.tasks_sql_transfer import lock_document, run
from bench.run_guided_repair import file_hash, write_report

FIXTURES = Path(__file__).with_name("phase4_tasks_dev")
ROOT = FIXTURES.parents[1]
LOCK = ROOT / "akasha_brain" / "protocols" / "tasks-rbitnet-sql-v4.json"
GOAL = ROOT / "contracts" / "examples" / "goal_tasks_repair.json"
FILES = ("schema.sql", "repair.py", "oracle.py", "cases.json")


def prepare_case(case: dict, folder: Path) -> None:
    folder.mkdir(parents=True)
    goal = json.loads(GOAL.read_bytes())
    goal.update(goal_id=case["goal_id"], user_intent=case["intent"])
    (folder / "goal.json").write_text(json.dumps(goal, ensure_ascii=False), encoding="utf-8")
    state = {key: case[key] for key in ("id", "rows", "visible_ids")}
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    for name in ("schema.sql", "repair.py", "oracle.py"):
        shutil.copyfile(FIXTURES / name, folder / name)


def measure(report: dict, case: dict) -> dict:
    local = next((step.get("result") for step in report["trace"] if step["id"] == "localize"), None)
    witness = report.get("reference")
    attempts = {}
    for step in report["trace"]:
        if step["id"] == "generate_diff":
            attempt = step["attempt"]
            result = step["result"]
            attempts[attempt] = {key: result[key] for key in ("diff_applied", "inferences", "targets")}
            if "rejected" in result:
                attempts[attempt]["rejected"] = result["rejected"]
            if result["diff_applied"]:
                attempts[attempt]["git_verified"] = result["git_apply_check"] and result["guest_sha256_verified"]
        if step["id"] == "verify":
            attempts[step["attempt"]]["verification"] = step.get("result")
    observed = bool(
        not report.get("error") and report.get("sandbox_stopped") and report.get("sandbox_id")
        and report["inference_backend"] == "cpu" and report["evolution"] == "excluded"
        and report["isolation"]["read_only_input"] and local and witness and attempts
        and [key for key, valid in local["filters"].items() if not valid] == [case["target"]]
        and local["sqlite_unchanged"] and all(witness["filters"].values()) and witness["sqlite_unchanged"]
        and all(not row["diff_applied"] or (row["git_verified"] and row["verification"]["sqlite_unchanged"])
                for row in attempts.values())
    )
    return {
        "evaluated": observed, "status": report["status"], "sandbox_id": report.get("sandbox_id"),
        "sandbox_stopped": report.get("sandbox_stopped"), "error": report.get("error"),
        "evolution": report["evolution"], "accepted_attempt": report["accepted_attempt"], "total_s": report["wall_s"],
        "initial": local, "witness": witness, "attempts": attempts,
    }


def campaign(runtime: Path, rbitnet: RbitnetPaths, output: Path) -> dict:
    frozen = json.loads(LOCK.read_bytes())
    if {**lock_document(None), "cuda_library_sha256": frozen["cuda_library_sha256"]} != frozen:
        raise RuntimeError("La référence Tâches a changé depuis le gel SQL v4.")
    sha = {name: file_hash(FIXTURES / name) for name in FILES}
    output.mkdir(parents=True)
    result = {"status": "running", "graph": "tasks-rbitnet-sql@1.3.0", "backend": "cpu",
              "protocol_sha256": file_hash(LOCK), "fixtures_sha256": sha, "runs": {}}
    write_report(output, result)
    cases = json.loads((FIXTURES / "cases.json").read_bytes())["cases"]
    for case in cases:
        tag = case["id"]
        fixture = output / "cases" / tag
        prepare_case(case, fixture)
        print(f"Référence CPU {tag}, cible {case['target']}", flush=True)
        runs = []
        result["runs"][tag] = {"target": case["target"], "executions": runs}
        for label in (tag, f"{tag}-recheck"):
            report = run(fixture, frozen, runtime, output / label, rbitnet, "cpu", None)
            measured = measure(report, case)
            runs.append(measured)
            write_report(output, result)
            print(json.dumps({key: measured[key] for key in ("evaluated", "status", "accepted_attempt", "total_s")},
                             ensure_ascii=False), flush=True)
            error = (report.get("error") or {}).get("message", "")
            if not (report.get("sandbox_stopped") and not report["trace"] and error.startswith("wsb start (")
                    and "timed out" in error):
                break
    if {name: file_hash(FIXTURES / name) for name in FILES} != sha or file_hash(LOCK) != result["protocol_sha256"]:
        raise RuntimeError("Le protocole ou les cas de développement ont changé pendant la mesure.")
    final = [case["executions"][-1] for case in result["runs"].values()]
    result["evaluated_cases"] = sum(run["evaluated"] for run in final)
    result["accepted_first_attempt"] = sum(run["evaluated"] and run["accepted_attempt"] == 1 for run in final)
    result["accepted_after_repair"] = sum(run["evaluated"] and run["accepted_attempt"] is not None for run in final)
    result["status"] = ("passed" if all(run["evaluated"] for run in final)
                        and len({run["sandbox_id"] for run in final}) == len(cases) else "incomplete")
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", type=Path, nargs=3, required=True, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rbitnet = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet))
    result = campaign(args.runtime.resolve(strict=True), rbitnet, args.output.resolve())
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
