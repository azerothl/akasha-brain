"""Exerce le repli global sur des politiques qualifiées et de nouvelles actions Notes."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import secrets
from time import monotonic, perf_counter
from uuid import uuid4

from akasha_brain import memory_workflows
from akasha_brain.bounded_evolution import BoundedEvolution, Observation, Policy, SandboxScope, STAGES
from akasha_brain.experience import transaction
from akasha_brain.integrated_evolution import IntegratedEvolution
from akasha_brain.memory_policy import CONTEXTUAL, PolicyWorkflowLibrary
from akasha_brain.notes_evolution import CANDIDATE as DESKTOP_GRAPH, GOAL_FILE
from akasha_brain.notes_link_promotion import digest, disposable_signer
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.notes_sandbox import read_profile
from akasha_brain.planning import ENVIRONMENT, compile_goal, load_catalog
from bench.run_guided_repair import BENCH, file_hash, write_report
from bench.run_notes_link_promotion import verify_chain
from bench.run_phase5_notes_action_selection import PROTOCOL, isolated_notes_sandbox, run_arm
from bench.run_phase5_notes_monitor import CASE
from bench.run_phase6_notes_evolution import observe_trial, stage_bench
from bench.run_phase6_skill_evolution import DESKTOP, MODEL_RAM_MIB, exercise, prepare_library

ARCHIVES = {"route": "phase6-notes-evolution-v1", "skill": "phase6-skill-evolution-v1", "memory": "phase6-memory-policy-v1"}


def archive(folder: Path, family: str) -> tuple[dict, str]:
    proof = folder / "report.json"
    fingerprint = file_hash(proof)
    if fingerprint != file_hash(BENCH / "results" / f"{ARCHIVES[family]}.json"):
        raise RuntimeError(f"Relevé {family} différent de l'archive de qualification.")
    report = json.loads(proof.read_bytes())
    log = folder / ("policy.sqlite" if family == "memory" else "evolution.sqlite")
    if report["status"] != "passed" or verify_chain(log) != report["events"]:
        raise RuntimeError(f"Journal {family} non vérifié.")
    if family != "memory":
        decision = report["stages"]["limited"]["assessment"]["decision"]["document"]
        previous = BoundedEvolution(log, decision["cycle"], Policy(**report["policy"]), report["public_key"])
        recorded = [{"stage": stage, "sha256": digest({key: value for key, value in report["stages"][stage]["assessment"].items()
                                                        if key != "decision"})} for stage in STAGES]
        if (previous.active() != previous.policy.parent or not all(report["checks"].values())
                or decision["stages"] != recorded):
            raise RuntimeError(f"Décisions archivées {family} non vérifiées.")
    else:
        with transaction(log) as db:
            proof_row = db.execute("SELECT proof FROM rejected_proofs WHERE stage = 'replay'").fetchone()
        if proof_row is None or json.loads(proof_row[0]) != report["assessment"]:
            raise RuntimeError("Le verdict de refus mémoire diffère du journal.")
    return report, fingerprint


def restore_qualification(coordinator: IntegratedEvolution, family: str, report: dict, sign) -> None:
    stages = report["stages"] if family != "memory" else {"replay": {"assessment": report["assessment"]}}
    for step, stage in stages.items():
        receipts = tuple(Observation(**entry) for entry in stage["assessment"]["receipts"])
        with coordinator.qualification(family) as cycle:
            if family == "skill":
                batch = str(uuid4())
                if not cycle.reserve_batch(step, batch):
                    raise RuntimeError("Réservation de compétence refusée.")
                for item in receipts:
                    scope = SandboxScope(item.sandbox_id, ENVIRONMENT, "R1", True, True)
                    if not cycle.admit_trial(step, batch, scope, item.case, item.version):
                        raise RuntimeError("Rejeu d'une preuve de compétence refusé.")
                verdict = cycle.complete_batch(step, batch, receipts, sign)
            else:
                scope = SandboxScope(receipts[0].sandbox_id, ENVIRONMENT,
                                     "R0" if family == "memory" else "R1", True, True)
                if not cycle.reserve(step, scope):
                    raise RuntimeError("Réservation du rejeu refusée.")
                verdict = cycle.complete_stage(step, scope, receipts, sign)
            if verdict["qualified"] != stage["assessment"]["qualified"]:
                raise RuntimeError(f"Verdict différent après rejeu de la preuve {family}/{step}.")


def run(sources: dict[str, Path], phase1: Path, runtime: Path, repair: RbitnetPaths, output: Path) -> dict:
    began = perf_counter()
    output.mkdir(parents=True)
    archived, hashes = {}, {}
    for family, folder in sources.items():
        archived[family], hashes[family] = archive(folder, family)
    policies = {family: replace(Policy(**report["policy"]),
                                freeze_sha256=digest({"prior": report["policy"]["freeze_sha256"],
                                                      "archive": hashes[family]}))
                for family, report in archived.items()}
    inputs = stage_bench(output / "input", runtime)
    inputs.update(integrated_runner=Path(__file__),
                  integrated_authority=BENCH.parent / "akasha_brain/integrated_evolution.py",
                  memory_policy=BENCH.parent / "akasha_brain/memory_policy.py",
                  skill_runner=BENCH / "run_phase6_skill_evolution.py")
    stage = output / "input"
    tag = secrets.token_hex(4)
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    report = {"protocol": "phase6-integrated-v1", "status": "running", "archives_sha256": hashes,
              "inputs_sha256": {name: file_hash(path) for name, path in inputs.items()},
              "sandbox": {}, "drift": {}, "checks": {}}

    def persist():
        write_report(output, report)

    persist()
    try:
        with disposable_signer() as (public_key, sign):
            cycles = {family: BoundedEvolution(output / f"{family}.sqlite", str(uuid4()), policy, public_key)
                      for family, policy in policies.items()}
            for cycle in cycles.values():
                cycle.initialize()
            path = output / "integrated.sqlite"
            coordinator = IntegratedEvolution(path, cycles)
            coordinator.initialize()
            for family in ARCHIVES:
                restore_qualification(coordinator, family, archived[family], sign)
            report["before"] = coordinator.status()
            if report["before"]["effective"] != {family: policy.parent if family == "memory" else policy.candidate
                                                  for family, policy in policies.items()}:
                raise RuntimeError("Les candidats attendus ne sont pas actifs après rejeu des preuves.")
            persist()

            protocol = json.loads(PROTOCOL.read_bytes())
            case, = (case for case in protocol["cases"] if case["id"] == CASE)
            with isolated_notes_sandbox(stage, tag, read_profile(), report["sandbox"], persist) as (sandbox, mount):
                scope = SandboxScope(sandbox, ENVIRONMENT, "R1", True, True)
                try:
                    coordinator.select("skill", replace(scope, risk_class="R3"), DESKTOP)
                except PermissionError:
                    report["checks"]["r3_refused"] = True
                route = coordinator.select("route", scope, CASE)
                run_arm(sandbox, fr"{mount}\faulty", case, protocol["plans"], route, report["drift"], persist)
                receipt = observe_trial(sandbox, case, route, report["drift"])
                report["drift"]["mismatches"] = list(receipt.mismatches)
                report["after_drift"] = coordinator.observe("route", scope, receipt, sign)
                try:
                    with coordinator.qualification("memory"):
                        report["checks"]["new_promotion_suspended"] = False
                except PermissionError:
                    report["checks"]["new_promotion_suspended"] = True
            persist()

            goal, catalog = json.loads(GOAL_FILE.read_bytes()), load_catalog()
            library, _, _ = prepare_library(phase1, output)
            plan = compile_goal(goal, catalog, rbitnet=True, rapidocr=True)
            comparable = digest({"inputs": memory_workflows.trial_files(runtime=runtime),
                                 "plan": memory_workflows.plan_contract(plan)})
            version = coordinator.status()["effective"]["skill"]
            _, receipt, detail = exercise(
                library, goal, catalog, runtime, output / "fallback_generation", repair, DESKTOP, version,
                comparable, lambda scope: coordinator.select("skill", scope, DESKTOP) == version, monotonic() + 300,
            )
            report["skill_fallback"] = {"selected": version, **detail}
            report["checks"]["skill_generation_reverified"] = (
                receipt.verified and version == policies["skill"].parent
                and detail["outcome"] == archived["skill"]["stages"]["replay"]["trials"][version]["outcome"]
            )
            state = memory_workflows.observe(runtime, True)
            memory_version = coordinator.status()["effective"]["memory"]
            selection = PolicyWorkflowLibrary(library.memory, memory_version).compare(goal, catalog, state)["gated"]
            report["memory_fallback"] = {"selected_policy": memory_version, "graph": selection["graph"]}
            report["checks"]["contextual_memory_retained"] = memory_version == CONTEXTUAL and selection["graph"] == DESKTOP_GRAPH
        report["reopened"] = IntegratedEvolution(path, cycles).status()
        report["checks"].update(
            drift_observed=set(report["drift"]["mismatches"]) == {"sqlite.row_count", "sqlite.exact_fixture_present"},
            effective_parents_persist=report["reopened"]["autonomy_phase"] == 3
                and report["reopened"]["effective"] == {family: policy.parent for family, policy in policies.items()}
                and set(report["reopened"]["rollback_proofs"]) == {"route"},
            unchanged_sources=report["inputs_sha256"] == {name: file_hash(p) for name, p in inputs.items()},
        )
        if not all(report["checks"].values()) or not report["checks"].get("r3_refused"):
            raise RuntimeError(f"Cycle intégré incomplet : {report['checks']}")
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
    for name in (*ARCHIVES, "phase1", "runtime", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--rbitnet", required=True, nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    args = parser.parse_args()
    sources = {name: getattr(args, name).resolve(strict=True) for name in ARCHIVES}
    repair = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet), model_ram_mib=MODEL_RAM_MIB)
    report = run(sources, args.phase1.resolve(strict=True), args.runtime.resolve(strict=True), repair, args.output.resolve())
    print(json.dumps({"status": report["status"], "wall_s": report["wall_s"], "checks": report["checks"]}), flush=True)


if __name__ == "__main__":
    main()
