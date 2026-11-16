"""Exerce les paliers signés du lien Notes dans six bacs Windows neufs."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from akasha_brain.experience import transaction
from akasha_brain.memory_workflows import measured_outcome
from akasha_brain.notes_evolution import evidence
from akasha_brain.notes_link_candidate import ADAPTER_STEP
from akasha_brain.notes_link_promotion import NotesLinkPromotion, digest, disposable_signer, verify_signature
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.notes_runtime import run_notes
from akasha_brain.planning import ENVIRONMENT
from bench.run_guided_repair import CHECKPOINTS, execution_limits, file_hash, write_report
from bench.run_notes_link_comparison import CPU_THREADS, MODEL_RAM_MIB, compile_graphs, require_freeze


def normalized_outcome(report: dict) -> dict:
    outcome = measured_outcome(report)
    outcome["steps"] = [step for step in outcome["steps"] if step["id"] != ADAPTER_STEP]
    return outcome


def verify_chain(registry: Path) -> list[str]:
    previous = None
    events = []
    with transaction(registry) as db:
        for payload, checksum in db.execute("SELECT payload, digest FROM evolution_events ORDER BY seq"):
            entry = json.loads(payload)
            if entry["previous"] != previous or sha256(payload.encode()).hexdigest() != checksum:
                raise RuntimeError("La chaîne d'audit du registre est invalide.")
            events.append(entry["event"])
            previous = checksum
    return events


def run(runtime: Path, repair: RbitnetPaths, output: Path, lock: Path, reference: Path) -> dict:
    lock_text = lock.read_text(encoding="utf-8")
    frozen = json.loads(lock_text)
    freeze_hash = sha256(lock_text.encode()).hexdigest()
    historical = json.loads(reference.read_bytes())
    goal, catalog, graphs = compile_graphs()
    require_freeze(frozen, graphs)
    if (historical["status"] != "passed" or historical["verified_pairs"] != 3 or historical["distinct_sandboxes"] != 6
            or historical["freeze_sha256"] != freeze_hash):
        raise RuntimeError("La comparaison publiée ne qualifie pas ce gel.")
    history = {pair["seed"]: pair for pair in historical["pairs"] if pair["status"] == "passed"}
    seeds = [entry["seed"] for entry in frozen["schedule"]]
    if set(history) != set(seeds) or repair.backend != "cpu":
        raise RuntimeError("Les références ou le moteur diffèrent du protocole figé.")
    replay_seed, shadow_seed, limited_seed = seeds

    output.mkdir(parents=True)
    registry = output / "promotion.sqlite"
    result = {"status": "running", "freeze_sha256": freeze_hash, "proofs": {}, "decisions": {}}
    all_ids = {row["sandbox_id"] for pair in historical["pairs"] for row in pair["runs"].values()}
    with disposable_signer() as (public_key, sign):
        controller = NotesLinkPromotion(registry, str(uuid4()), graphs, freeze_hash, file_hash(reference), public_key)
        controller.initialize()
        result["public_key"] = public_key
        result["initial_active"] = controller.active()
        write_report(output, result)

        def trial(stage: str, selected: str, seed: int) -> dict:
            require_freeze(frozen, compile_graphs()[2])
            if sha256(lock.read_text(encoding="utf-8").encode()).hexdigest() != freeze_hash:
                raise RuntimeError("Le fichier de gel a changé.")
            if file_hash(reference) != controller.reference_sha256:
                raise RuntimeError("Les résultats historiques ont changé.")
            arm = {controller.parent: "parent", controller.candidate: "candidate"}[selected]
            print(f"{stage} {arm} graine {seed}", flush=True)
            with execution_limits(None, cpu_threads=CPU_THREADS, model_ram_mb=MODEL_RAM_MIB):
                report = run_notes(goal, catalog, runtime, output / stage, repair, rapidocr=True, first_diff_seed=seed,
                                   origin=f"link_promotion_{stage}", link_candidate=arm == "candidate")
            outcome = normalized_outcome(report)
            links = report["link_diagnostics"]["links"]
            verified = (
                report["graph"] == graphs[arm] and evidence(report, desktop=True)["verified"]
                and len(links) == len(graphs[arm]["steps"]) - 1 and all(link["status"] == "verified" for link in links)
                and report["repair"]["backend"] == "cpu" and report["repair"]["hashes"] == CHECKPOINTS
                and report["repair"]["seeds"] == (seed,) and outcome == history[seed]["common_outcome"]
                and bool(report.get("sandbox_id")) and report["sandbox_id"] not in all_ids
            )
            if not verified:
                raise RuntimeError(f"Le palier {stage} a échoué. Consulter son rapport.")
            all_ids.add(report["sandbox_id"])
            proof = {
                "verified": True, "arm": arm, "seed": seed, "graph_id": selected,
                "graph_version": report["graph"]["graph_version"], "sandbox_id": report["sandbox_id"],
                "sandbox_stopped": report["sandbox_stopped"], "total_s": report["wall_s"],
                "report_sha256": file_hash(output / stage / "report.json"), "outcome_sha256": digest(outcome),
                "first_diff_applied": report["accepted_attempt"] == 1 and outcome["diff_applied"],
                "diff_sha256": outcome["diff_sha256"], "tests": outcome["tests"], "sqlite": outcome["sqlite"],
                "desktop": outcome["desktop"], "links": len(links), "active": controller.active(),
            }
            result["proofs"][stage] = proof
            write_report(output, result)
            print(json.dumps({"stage": stage, "verified": True, "total_s": proof["total_s"]}), flush=True)
            return proof

        try:
            controller.prepare("promote")
        except RuntimeError:
            result["premature_promotion_refused"] = True
        else:
            raise RuntimeError("La promotion était autorisée avant les preuves.")

        controller.record_trial("replay", trial("replay", controller.candidate, replay_seed))
        controller.record_trial("shadow_parent", trial("shadow_parent", controller.active(), shadow_seed))
        controller.record_trial("shadow_candidate", trial("shadow_candidate", controller.candidate, shadow_seed))
        if controller.active() != controller.parent:
            raise RuntimeError("L'exécution shadow a modifié le graphe actif.")
        outside = controller.limited_route(ENVIRONMENT, eligible=False)
        admitted = controller.limited_route(ENVIRONMENT, eligible=True)
        exhausted = controller.limited_route(ENVIRONMENT, eligible=True)
        if (outside, admitted, exhausted) != (controller.parent, controller.candidate, controller.parent):
            raise RuntimeError("Le routage limité n'a pas respecté son périmètre ou son budget.")
        result["limited_routes"] = {"outside_cohort": outside, "admitted": admitted, "after_quota": exhausted}
        controller.record_trial("limited", trial("limited", admitted, limited_seed))

        decision = controller.prepare("promote")
        signature = sign(decision)
        tampered = {**decision, "freeze_sha256": "0" * 64}
        try:
            controller.apply(tampered, signature)
        except RuntimeError as error:
            if str(error) != "Signature Ed25519 invalide." or controller.active() != controller.parent:
                raise
            result["tampered_decision_refused"] = True
        else:
            raise RuntimeError("La décision altérée a été acceptée.")
        controller.apply(decision, signature)
        result["decisions"]["promote"] = {"document": decision, "signature": signature}
        result["promoted_active"] = controller.active()
        write_report(output, result)
        try:
            trial("active", controller.active(), limited_seed)
        finally:
            rollback = controller.prepare("rollback")
            rollback_signature = sign(rollback)
            controller.apply(rollback, rollback_signature)
            result["decisions"]["rollback"] = {"document": rollback, "signature": rollback_signature}
            result["restored_active"] = controller.active()
            write_report(output, result)
        trial("after_rollback", controller.active(), limited_seed)

    for packet in result["decisions"].values():
        if not verify_signature(packet["document"], packet["signature"], public_key):
            raise RuntimeError("Une signature archivée a échoué à la revérification.")
    result["signatures_reverified"] = True
    result["events"] = verify_chain(registry)
    result["distinct_new_sandboxes"] = len(all_ids) - historical["distinct_sandboxes"]
    if result["distinct_new_sandboxes"] != 6 or result["restored_active"] != controller.parent:
        raise RuntimeError("Le nombre de bacs ou le retour arrière n'est pas confirmé.")
    result["status"] = "passed"
    write_report(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", nargs=3, type=Path, required=True, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    repair = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet), model_ram_mib=MODEL_RAM_MIB)
    result = run(args.runtime.resolve(strict=True), repair, args.output.resolve(), args.lock, args.reference)
    print(json.dumps({key: result[key] for key in ("status", "promoted_active", "restored_active",
                                                   "distinct_new_sandboxes", "signatures_reverified")}))


if __name__ == "__main__":
    main()
