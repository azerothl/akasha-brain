"""Compare l'adaptateur de liaison Notes au graphe parent en bacs neufs."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

from akasha_brain.memory_workflows import measured_outcome
from akasha_brain.notes_evolution import GOAL_FILE, evidence
from akasha_brain.notes_link_candidate import ADAPTER_STEP, compile_candidate
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.notes_runtime import run_notes
from akasha_brain.planning import compile_goal, load_catalog
from bench.run_guided_repair import CHECKPOINTS, MAX_TOKENS, TEMPERATURE, execution_limits, file_hash, write_report

ROOT = Path(__file__).resolve().parents[1]
ORDER = ("parent", "candidate")
CPU_THREADS = 8
MODEL_RAM_MIB = 8192
SCHEDULE = (
    {"seed": 742, "order": list(ORDER)},
    {"seed": 743, "order": list(reversed(ORDER))},
    {"seed": 744, "order": list(ORDER)},
)
FROZEN_FILES = (
    "akasha_brain/capabilities.json", "akasha_brain/planning.py", "akasha_brain/experience.py",
    "akasha_brain/link_diagnostics.py", "akasha_brain/notes_link_candidate.py", "akasha_brain/notes_runtime.py",
    "akasha_brain/notes_evolution.py", "akasha_brain/notes_repair.py", "akasha_brain/notes_sandbox.py",
    "akasha_brain/notes_desktop.py", "akasha_brain/model_resources.py", "akasha_brain/memory_workflows.py",
    "akasha_brain/prompts/notes-repair-v1.json", "akasha_brain/protocols/notes-desktop-ocr-v2.json",
    "bench/run_guided_repair.py", "bench/run_notes_link_comparison.py",
    "bench/harness/akasha-bench.wsb", "bench/harness/validate_guided_notes.ps1",
    "bench/harness/probe_notes_isolation.ps1", "bench/harness/probe_guest_channels.ps1",
    "bench/harness/notes_ocr_guest.py", "bench/harness/measure_ocr.py",
    "bench/harness/run_notes_ocr.ps1", "bench/harness/read_notes_ocr_error.ps1",
    "bench/notes/notes_store.py", "bench/notes/notes_app.py", "bench/notes/conftest.py",
    "bench/notes/tests/test_notes.py", "bench/notes/tests/test_ui.py", "bench/notes/verifiers/verify_notes.py",
    "contracts/examples/goal_notes_regression.json",
    "contracts/schemas/GoalSpec/v1.0.0.json", "contracts/schemas/CapabilityManifest/v1.0.0.json",
    "contracts/schemas/ExperienceRecord/v1.0.0.json",
    "contracts/akasha_contracts/authz.py", "contracts/akasha_contracts/validate.py",
)


def compile_graphs():
    goal = json.loads(GOAL_FILE.read_bytes())
    catalog = load_catalog()
    parent = compile_goal(goal, catalog, rbitnet=True, rapidocr=True)
    return goal, catalog, {"parent": parent, "candidate": compile_candidate(parent)}


def freeze_document(snapshots) -> dict:
    return {
        "version": 1,
        "graphs": snapshots,
        "files": {name: sha256((ROOT / name).read_text(encoding="utf-8").encode()).hexdigest()
                  for name in FROZEN_FILES},
        "rbitnet": {"backend": "cpu", "hashes": CHECKPOINTS, "cpu_threads": CPU_THREADS,
                    "model_ram_mib": MODEL_RAM_MIB, "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE},
        "schedule": list(SCHEDULE),
    }


def require_freeze(frozen: dict, snapshots) -> None:
    current = freeze_document(snapshots)
    if current != frozen:
        changed = [key for key, value in current["files"].items() if value != frozen.get("files", {}).get(key)]
        detail = ", ".join(changed) if changed else "graphes ou protocole"
        raise RuntimeError(f"Le gel de l'adaptateur a dérivé ({detail}).")


def compare(runtime: Path, repair: RbitnetPaths, output: Path, seed: int, *, order=ORDER, frozen=None) -> dict:
    if repair.backend != "cpu" or repair.model_ram_mib != MODEL_RAM_MIB:
        raise ValueError("La comparaison exige Rbitnet CPU avec un plafond de 8 192 Mio.")
    output.mkdir(parents=True)
    goal, catalog, snapshots = compile_graphs()
    measurements = {"status": "running", "seed": seed, "cpu_threads": CPU_THREADS, "model_ram_mib": MODEL_RAM_MIB,
                    "order": list(order), "pairs": 1, "runs": {}}
    reports = {}
    for arm, graph in snapshots.items():
        plan = output / f"{arm}-graph.json"
        plan.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(output, measurements)
    for arm in order:
        if frozen is not None:
            require_freeze(frozen, snapshots)
        graph = snapshots[arm]
        print(f"{seed} {arm} {graph['graph_id']}@{graph['graph_version']}", flush=True)
        with execution_limits(None, cpu_threads=CPU_THREADS, model_ram_mb=MODEL_RAM_MIB):
            report = run_notes(goal, catalog, runtime, output / arm, repair, rapidocr=True, first_diff_seed=seed,
                               origin="link_comparison", link_candidate=arm == "candidate")
        verified = evidence(report, desktop=True)["verified"]
        links = report["link_diagnostics"]["links"]
        proposal = next((row.get("result", {}) for row in report["trace"] if row["id"] == "generate_diff"), {})
        engine = report.get("repair", {})
        verified = (report["graph"] == graph and verified and len(links) == len(graph["steps"]) - 1
                    and all(link["status"] == "verified" for link in links) and proposal.get("seed") == seed
                    and engine.get("backend") == "cpu" and engine.get("hashes") == CHECKPOINTS)
        reports[arm] = report
        measurements["runs"][arm] = {
            "graph_id": graph["graph_id"], "version": graph["graph_version"],
            "graph_sha256": file_hash(output / f"{arm}-graph.json"),
            "verified": verified, "sandbox_id": report.get("sandbox_id"), "error": report.get("error"),
            "steps_s": {row["id"]: row["wall_s"] for row in report["trace"]},
            "links": links, "accepted_attempt": report.get("accepted_attempt"),
            "total_s": report["wall_s"],
            "rbitnet_startup_s": proposal.get("startup_s"), "rbitnet_generation_s": proposal.get("generation_s"),
            "outcome": measured_outcome(report),
        }
        write_report(output, measurements)
        print(json.dumps({"seed": seed, "arm": arm, "verified": verified, "total_s": report["wall_s"]}), flush=True)

    baseline, candidate = reports["parent"], reports["candidate"]
    separate = bool(baseline.get("sandbox_id") and candidate.get("sandbox_id")
                    and baseline["sandbox_id"] != candidate["sandbox_id"])
    matched = all(baseline.get(key) is not None and baseline[key] == candidate.get(key)
                  for key in ("repair", "protocol", "ocr"))
    common = measured_outcome(baseline)
    adapted = measured_outcome(candidate)
    adapted["steps"] = [row for row in adapted["steps"] if row["id"] != ADAPTER_STEP]
    receipt = next((row.get("result") for row in candidate["trace"]
                    if row["id"] == ADAPTER_STEP and row["status"] == "passed"), None)
    same = bool(adapted == common and receipt and receipt["diff_sha256"] == common["diff_sha256"])
    passed = separate and matched and same and all(row["verified"] for row in measurements["runs"].values())
    parent_steps = measurements["runs"]["parent"]["steps_s"]
    candidate_steps = measurements["runs"]["candidate"]["steps_s"]
    measurements.update(
        status="passed" if passed else "failed", same_diff_and_checks=same,
        separate_sandboxes=separate, matched_inputs=matched, adapter=receipt,
        common_outcome=common if same else None,
        candidate_minus_parent_s={step: round(candidate_steps[step] - seconds, 3)
                                  for step, seconds in parent_steps.items() if step in candidate_steps},
        total_delta_s=round(candidate["wall_s"] - baseline["wall_s"], 3),
    )
    write_report(output, measurements)
    return measurements


def campaign(runtime: Path, repair: RbitnetPaths, output: Path, lock: Path) -> dict:
    frozen = json.loads(lock.read_bytes())
    require_freeze(frozen, compile_graphs()[2])
    output.mkdir(parents=True)
    results = {"status": "running", "freeze_sha256": file_hash(lock), "pairs": []}
    write_report(output, results)
    for trial in frozen["schedule"]:
        seed = trial["seed"]
        results["pairs"].append(compare(runtime, repair, output / f"seed-{seed}", seed,
                                        order=trial["order"], frozen=frozen))
        write_report(output, results)
    require_freeze(json.loads(lock.read_bytes()), compile_graphs()[2])
    if file_hash(lock) != results["freeze_sha256"]:
        raise RuntimeError("Le manifeste de gel a changé pendant la campagne.")

    pairs = results["pairs"]
    ids = {row["sandbox_id"] for pair in pairs for row in pair["runs"].values() if row["sandbox_id"]}
    verified = [pair for pair in pairs if pair["status"] == "passed"]
    results.update(status="passed" if len(verified) == len(SCHEDULE) and len(ids) == 2 * len(SCHEDULE) else "failed",
                   distinct_sandboxes=len(ids), verified_pairs=len(verified))
    if verified:
        results["median_steps_s"] = {
            arm: {step: median(pair["runs"][arm]["steps_s"][step] for pair in verified)
                  for step in verified[0]["runs"][arm]["steps_s"]}
            for arm in ORDER
        }
        results["median_paired_delta_s"] = {
            step: median(pair["candidate_minus_parent_s"][step] for pair in verified)
            for step in verified[0]["candidate_minus_parent_s"]
        }
        results["median_total_s"] = {arm: median(pair["runs"][arm]["total_s"] for pair in verified) for arm in ORDER}
        results["median_total_delta_s"] = median(pair["total_delta_s"] for pair in verified)
        results["median_conversion_ms"] = median(pair["adapter"]["conversion_ms"] for pair in verified)
    write_report(output, results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--rbitnet", type=Path, nargs=3, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seed", type=int)
    mode.add_argument("--write-freeze", type=Path)
    mode.add_argument("--campaign", type=Path, metavar="GEL")
    args = parser.parse_args()
    if args.write_freeze:
        with args.write_freeze.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(freeze_document(compile_graphs()[2]), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return 0
    if not (args.runtime and args.rbitnet and args.output):
        parser.error("--runtime, --rbitnet et --output sont requis pour les essais.")
    if args.seed is not None and args.seed < 0:
        parser.error("La graine doit être positive ou nulle.")
    repair = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet), model_ram_mib=MODEL_RAM_MIB)
    runtime, output = args.runtime.resolve(strict=True), args.output.resolve()
    if args.campaign:
        result = campaign(runtime, repair, output, args.campaign.resolve(strict=True))
        print(json.dumps({key: value for key, value in result.items() if key != "pairs"}, ensure_ascii=False, indent=2))
    else:
        result = compare(runtime, repair, output, 742 if args.seed is None else args.seed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
