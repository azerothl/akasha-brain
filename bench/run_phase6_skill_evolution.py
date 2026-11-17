"""Qualifie et surveille la réutilisation de la compétence Notes dans des bacs neufs."""

import argparse
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from time import monotonic, perf_counter
from uuid import uuid4

from akasha_brain import memory_workflows
from akasha_brain.bounded_evolution import BoundedEvolution, Policy, STAGES
from akasha_brain.memory import NotesMemory
from akasha_brain.notes_evolution import GOAL_FILE
from akasha_brain.notes_link_promotion import digest, disposable_signer, verify_signature
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.phase6_skill import CODE, DESKTOP, GENERATION as PARENT, REUSE as CANDIDATE, execute
from akasha_brain.planning import compile_goal, load_catalog
from bench.run_guided_repair import BENCH, file_hash, write_report
from bench.run_notes_link_promotion import verify_chain

CPU_THREADS, MODEL_RAM_MIB = 8, 8192
DEADLINE_S = 1200
MIN_SAVINGS_MS = 5000
# Cette mesure englobe la vérification locale de la décision Ed25519.
CONTROL_LIMIT_US = 2_000_000


def prepare_library(source: Path, output: Path) -> tuple[memory_workflows.WorkflowLibrary, str, dict]:
    memory = NotesMemory(output / "journal.sqlite")
    journal = (source / "registry.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(journal, uri=True)) as before, closing(sqlite3.connect(memory.path)) as copy:
        before.backup(copy)
    memory.initialize()
    captured = memory.capture()
    library = memory_workflows.WorkflowLibrary(memory)
    library.install()
    code_proofs = [source / name / "report.json" for name in ("cycle", "rollback-proof")]
    desktop_proofs = [source / "cycle" / "evolution" / name / "report.json" for name in STAGES]
    code = library.publish(code_proofs)
    desktop = library.publish(desktop_proofs)
    revoke = json.loads(desktop_proofs[0].read_bytes())["experience_record_id"]
    proofs = {path.relative_to(source).as_posix(): file_hash(path) for path in (*code_proofs, *desktop_proofs)}
    return library, revoke, {"capture": captured, CODE: code["proofs"], DESKTOP: desktop["proofs"], "proofs_sha256": proofs}


def exercise(library, goal, catalog, runtime, folder, repair, case, version, comparable, permit, deadline, *, erase=None):
    scope, receipt, detail, _ = execute(
        library, goal, catalog, runtime, folder, repair, case, version, comparable, permit, deadline,
        cpu_threads=CPU_THREADS, model_ram_mib=MODEL_RAM_MIB, erase=erase,
    )
    return scope, receipt, detail


def run(source: Path, runtime: Path, repair: RbitnetPaths, output: Path) -> dict:
    began, deadline = perf_counter(), monotonic() + DEADLINE_S
    output.mkdir(parents=True)
    library, erasure_source, published = prepare_library(source, output)
    goal = json.loads(GOAL_FILE.read_bytes())
    catalog = load_catalog()
    inputs = memory_workflows.trial_files(runtime=runtime)
    goals = {case: compile_goal(goal, catalog, rbitnet=True, rapidocr=case == DESKTOP) for case in (CODE, DESKTOP)}
    cases = {case: digest({"inputs": inputs, "plan": memory_workflows.plan_contract(plan)})
             for case, plan in goals.items()}
    files = (Path(__file__), GOAL_FILE, Path(memory_workflows.__file__), BENCH.parent / "akasha_brain/notes_runtime.py",
             BENCH.parent / "akasha_brain/bounded_evolution.py", BENCH.parent / "contracts/akasha_contracts/authz.py")
    hashes = {path.name: file_hash(path) for path in files}
    policy = Policy("skill", PARENT, CANDIDATE, digest({"sources": hashes, "cases": cases, "library": published}),
                    (DESKTOP,), (CODE,), DESKTOP, CONTROL_LIMIT_US, MIN_SAVINGS_MS)
    report = {"protocol": "phase6-skill-evolution-v1", "status": "running", "policy": asdict(policy),
              "sources_sha256": hashes, "library": published, "case_inputs_sha256": cases,
              "budget": {"max_sandboxes": 8, "wall_s": DEADLINE_S, "cpu_threads": CPU_THREADS,
                         "model_ram_mib": MODEL_RAM_MIB},
              "stages": {}, "live": {}}

    def persist():
        write_report(output, report)

    sandbox_ids = set()
    db = output / "evolution.sqlite"
    persist()
    try:
        with disposable_signer() as (public_key, sign):
            controller = BoundedEvolution(db, str(uuid4()), policy, public_key)
            controller.initialize()
            report["public_key"] = public_key

            def trial(case, version, name, permit, erase=None):
                scope, receipt, detail = exercise(library, goal, catalog, runtime, output / name, repair,
                                                  case, version, cases[case], permit, deadline, erase=erase)
                if scope.sandbox_id in sandbox_ids or len(sandbox_ids) >= report["budget"]["max_sandboxes"]:
                    raise RuntimeError("Le nombre ou l'identité des bacs dépasse le budget.")
                sandbox_ids.add(scope.sandbox_id)
                print(f"{name}: {version}, vérifié={receipt.verified}, {receipt.wall_ms / 1000:.3f} s", flush=True)
                return scope, receipt, detail

            for stage in STAGES:
                batch = str(uuid4())
                evidence = report["stages"][stage] = {"trials": {}}
                if not controller.reserve_batch(stage, batch):
                    raise RuntimeError(f"Palier {stage} non réservé.")
                case, = policy.cases(stage)
                order = {"replay": (PARENT, CANDIDATE), "shadow": (CANDIDATE, PARENT), "limited": (CANDIDATE,)}[stage]
                receipts = []
                for version in order:
                    _, receipt, detail = trial(
                        case, version, f"{stage}-{version}",
                        lambda scope: controller.admit_trial(stage, batch, scope, case, version),
                    )
                    receipts.append(receipt)
                    evidence["trials"][version] = detail
                    persist()
                evidence["assessment"] = controller.complete_batch(stage, batch, tuple(receipts), sign)
                evidence["active_after"] = controller.active()
                persist()
                if not evidence["assessment"]["qualified"]:
                    raise RuntimeError(f"Le gain ou le verdict du palier {stage} est insuffisant.")

            for name in ("nominal", "revocation", "after_rollback"):
                version = controller.active()
                expected = PARENT if name == "after_rollback" else CANDIDATE
                if version != expected:
                    raise RuntimeError("Compétence active différente du verdict attendu.")
                scope, receipt, detail = trial(
                    DESKTOP, version, name, lambda actual: controller.select(actual, DESKTOP) == version,
                    erase=erasure_source if name == "revocation" else None,
                )
                report["live"][name] = {**detail, "selected": version,
                                        "monitor": controller.observe(scope, receipt, sign)}
                if name == "revocation":
                    report["erasure"] = library.memory.finish_erasures()
                    compared = library.compare(goal, catalog, memory_workflows.observe(runtime, True))
                    report["erasure"]["desktop_reuse_unavailable"] = compared["gated"] is None
                persist()

        nominal, revoked, fallback = (report["live"][item] for item in ("nominal", "revocation", "after_rollback"))
        baseline = report["stages"]["replay"]["trials"][PARENT]["outcome"]
        signatures = (report["stages"]["limited"]["assessment"]["decision"], revoked["monitor"]["decision"])
        report["events"] = verify_chain(db)
        report["checks"] = {
            "one_promotion_one_rollback": report["events"].count("promote") == report["events"].count("rollback") == 1,
            "nominal_matches_baseline": nominal["outcome"] == baseline and not nominal["monitor"]["alerts"],
            "revoked_before_effect": revoked["before_effect"] and revoked["error"] == "erasure_requested"
                and revoked["monitor"]["active"] == PARENT,
            "revoked_skill_unavailable": report["erasure"]["desktop_reuse_unavailable"],
            "parent_reverified": controller.active() == PARENT and fallback["outcome"] == baseline,
            "signatures_verified": all(verify_signature(d["document"], d["signature"], public_key) for d in signatures),
            "sources_unchanged": hashes == {path.name: file_hash(path) for path in files},
            "distinct_sandboxes": len(sandbox_ids) == report["budget"]["max_sandboxes"],
        }
        if not all(report["checks"].values()):
            raise RuntimeError(f"Cycle de compétence incomplet : {report['checks']}")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["wall_s"] = round(perf_counter() - began, 3)
        persist()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--rbitnet", required=True, nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repair = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet), model_ram_mib=MODEL_RAM_MIB)
    report = run(args.phase1.resolve(strict=True), args.runtime.resolve(strict=True), repair, args.output.resolve())
    print(json.dumps({"status": report["status"], "wall_s": report["wall_s"], "checks": report["checks"]}), flush=True)


if __name__ == "__main__":
    main()
