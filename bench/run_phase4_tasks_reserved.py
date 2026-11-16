"""Fige puis compare le spécialiste SQL v3 et la référence sur des cas réservés."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from akasha_brain import tasks_sql_specialist_v3 as specialist
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.tasks_sql_specialist_v2 import verify_coverage
from akasha_brain.tasks_sql_transfer import CONFIGURATION, VERSION as REFERENCE_VERSION, lock_document, run as run_reference
from bench.run_guided_repair import CHECKPOINTS, file_hash, write_report
from bench.run_phase4_tasks_baseline import GOAL, LOCK as REFERENCE_LOCK, ROOT
from bench.run_phase4_tasks_specialist import GRAPH, RECHECK_TIMEOUT_S, measure_pair, run_case

LOCK = ROOT / "akasha_brain/protocols/tasks-sql-specialist-v3.json"
FIXTURES = ROOT / "bench/phase4_tasks_reserved"
TEMPLATES = ROOT / "bench/phase4_tasks_dev"
FILES = ("cases.json", "oracle.py")
FROZEN_FILES = (
    "akasha_brain/tasks_sql_specialist.py", "akasha_brain/tasks_sql_specialist_v2.py",
    "akasha_brain/tasks_sql_specialist_v3.py", "bench/run_phase4_tasks_specialist.py",
    "bench/run_phase4_tasks_baseline.py", "bench/run_phase4_tasks_reserved.py",
    "bench/phase4_tasks_dev/schema.sql", "bench/phase4_tasks_dev/repair.py",
    "bench/results/phase4-tasks-specialist-v3.json", "akasha_brain/protocols/tasks-rbitnet-sql-v4.json",
)


def freeze_document() -> dict:
    reference = json.loads(REFERENCE_LOCK.read_bytes())
    if {**lock_document(None), "cuda_library_sha256": reference["cuda_library_sha256"]} != reference:
        raise RuntimeError("La référence ne correspond pas au gel SQL v4.")
    return {
        "version": 1,
        "graphs": {"reference": f"tasks-rbitnet-sql@{REFERENCE_VERSION}", "v3": f"{GRAPH}@{specialist.VERSION}"},
        "files_sha256": {name: sha256((ROOT / name).read_text(encoding="utf-8").encode()).hexdigest()
                         for name in FROZEN_FILES},
        "runtime": {arm: {**CONFIGURATION, "timeout_s": timeout} for arm, timeout in (
            ("reference", CONFIGURATION["timeout_s"]), ("v3", RECHECK_TIMEOUT_S))},
        "weights_and_engine": CHECKPOINTS,
        "evolution": "excluded",
    }


def prepare(case: dict, directory: Path) -> None:
    directory.mkdir(parents=True)
    goal = json.loads(GOAL.read_bytes())
    goal.update(goal_id=case["goal_id"], user_intent=case["intent"])
    (directory / "goal.json").write_text(json.dumps(goal, ensure_ascii=False), encoding="utf-8")
    state = {field: case[field] for field in ("id", "rows", "visible_ids")}
    (directory / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    for name in ("schema.sql", "repair.py"):
        shutil.copyfile(TEMPLATES / name, directory / name)
    shutil.copyfile(FIXTURES / "oracle.py", directory / "oracle.py")


def verify_case(case: dict) -> None:
    if case["order"] not in (["reference", "v3"], ["v3", "reference"]):
        raise ValueError("L’ordre des bras doit être fixé dans le corpus.")
    verify_coverage(case["coverage"], case["coverage"])


def compare(runtime: Path, paths: RbitnetPaths, output: Path) -> dict:
    lock = json.loads(LOCK.read_bytes())
    if freeze_document() != lock or paths.backend != "cpu":
        raise RuntimeError("Le banc réservé exige le gel de la v3 et Rbitnet CPU.")
    lock_sha = file_hash(LOCK)
    reserved_hashes = {name: file_hash(FIXTURES / name) for name in FILES}
    corpus = json.loads((FIXTURES / "cases.json").read_bytes())
    if corpus["freeze_sha256"] != lock_sha or corpus["evolution"] != "excluded":
        raise ValueError("Le corpus doit être lié au gel et rester hors évolution.")
    cases = corpus["cases"]
    if len(cases) != 2 or len({case["id"] for case in cases}) != 2 or cases[0]["order"] == cases[1]["order"]:
        raise ValueError("Deux cas réservés et un ordre alterné sont requis.")
    for case in cases:
        verify_case(case)

    output.mkdir(parents=True)
    result = {"status": "running", "freeze_sha256": lock_sha, "reserved_sha256": reserved_hashes,
              "graphs": lock["graphs"], "runtime": lock["runtime"], "evolution": "excluded", "runs": {}}
    write_report(output, result)
    reference_lock = json.loads(REFERENCE_LOCK.read_bytes())
    seen = set()
    for case in cases:
        tag = case["id"]
        folder = output / "cases" / tag
        prepare(case, folder)
        pair = {"target": case["target"], "order": case["order"], "arms": {}}
        result["runs"][tag] = pair
        for arm in case["order"]:
            if freeze_document() != lock or {name: file_hash(FIXTURES / name) for name in FILES} != reserved_hashes:
                raise RuntimeError("Le gel ou le corpus a changé pendant la campagne.")
            executions = pair["arms"][arm] = []
            for run_dir in (output / tag / arm, output / tag / f"{arm}-recheck"):
                print(f"{tag} {arm}, cible {case['target']}", flush=True)
                if arm == "v3":
                    report = run_case(folder, runtime, run_dir, paths, timeout_s=RECHECK_TIMEOUT_S,
                                      required=case["coverage"], v3=True)
                else:
                    report = run_reference(folder, reference_lock, runtime, run_dir, paths, "cpu", None)
                # Le témoin propre à chaque bac sera comparé à l'autre bras une fois les deux rapports obtenus.
                observed = measure_pair(report, case, {"initial": None, "witness": None}, seen)
                del observed["same_witness_and_initial"]
                executions.append(observed)
                seen.add(observed["sandbox_id"])
                write_report(output, result)
                print(json.dumps({key: observed[key] for key in ("evaluated", "status", "accepted_attempt", "total_s")}),
                      flush=True)
                error = (report.get("error") or {}).get("message", "")
                if not (report.get("sandbox_stopped") and "timed out" in error
                        and (not report["trace"] and error.startswith("wsb start (") or error == "timed out")):
                    break
        reference, candidate = (pair["arms"][arm][-1] for arm in ("reference", "v3"))
        pair["same_witness_and_initial"] = all(reference[key] == candidate[key] for key in ("initial", "witness"))
        pair["total_delta_s"] = round(candidate["total_s"] - reference["total_s"], 3)
        write_report(output, result)
    if freeze_document() != lock or file_hash(LOCK) != lock_sha or {
            name: file_hash(FIXTURES / name) for name in FILES} != reserved_hashes:
        raise RuntimeError("Le gel ou le corpus a changé en fin de campagne.")
    result["scores"] = {
        arm: {
            "evaluated": sum(row["arms"][arm][-1]["evaluated"] for row in result["runs"].values()),
            "first": sum(row["arms"][arm][-1]["accepted_attempt"] == 1 for row in result["runs"].values()),
            "final": sum(row["arms"][arm][-1]["accepted_attempt"] is not None for row in result["runs"].values()),
        } for arm in ("reference", "v3")
    }
    complete = all(row["same_witness_and_initial"] and all(runs[-1]["evaluated"] and runs[-1]["distinct_sandbox"]
                    for runs in row["arms"].values()) for row in result["runs"].values())
    result["status"] = "passed" if complete else "incomplete"
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze")
    replay = commands.add_parser("run")
    replay.add_argument("--runtime", type=Path, required=True)
    replay.add_argument("--rbitnet", type=Path, nargs=3, required=True)
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        document = freeze_document()
        with LOCK.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        print(file_hash(LOCK))
        return 0
    paths = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet))
    result = compare(args.runtime.resolve(strict=True), paths, args.output.resolve())
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
