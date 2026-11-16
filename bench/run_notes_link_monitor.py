"""Qualifie le retour arrière automatique du lien Notes dans Windows Sandbox."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from akasha_brain.notes_link_promotion import STAGES, NotesLinkPromotion, digest, disposable_signer, verify_signature
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.notes_runtime import run_notes
from akasha_brain.planning import ENVIRONMENT
from bench.run_guided_repair import execution_limits, file_hash, write_report
from bench.run_notes_link_comparison import CPU_THREADS, MODEL_RAM_MIB, ROOT, compile_graphs, require_freeze
from bench.run_notes_link_handoff import DESKTOP_FILE, LOCK_FILE, instrument, measure
from bench.run_notes_link_promotion import verify_chain

PROMOTION_FILE = ROOT / "bench" / "results" / "notes-link-promotion-v1.json"
FAILURE_LIMIT = 1


def published_proofs(graphs: dict, freeze_hash: str, archive: dict) -> dict:
    packet = archive["decisions"]["promote"]
    decision, signature = packet["document"], packet["signature"]
    proofs = {stage: archive["proofs"][stage] for stage in STAGES}
    if (archive["status"] != "passed" or decision["action"] != "promote" or decision["environment"] != ENVIRONMENT
            or decision["freeze_sha256"] != freeze_hash
            or decision["plans"] != {graph["graph_id"]: digest(graph) for graph in graphs.values()}
            or decision["trials"] != [{"stage": stage, "proof_sha256": digest(proof)} for stage, proof in proofs.items()]
            or not verify_signature(decision, signature, archive["public_key"])):
        raise RuntimeError("Les preuves de promotion publiées ne qualifient pas ce gel.")
    return proofs


def run(runtime: Path, repair: RbitnetPaths, output: Path) -> dict:
    lock_text = LOCK_FILE.read_text(encoding="utf-8")
    frozen = json.loads(lock_text)
    freeze_hash = sha256(lock_text.encode()).hexdigest()
    published_hash = file_hash(PROMOTION_FILE)
    archive = json.loads(PROMOTION_FILE.read_bytes())
    goal, catalog, graphs = compile_graphs()
    require_freeze(frozen, graphs)
    proofs = published_proofs(graphs, freeze_hash, archive)
    expected_diff = json.loads(DESKTOP_FILE.read_bytes())["diff_sha256"]
    sandbox_ids = {proof["sandbox_id"] for proof in archive["proofs"].values()}
    output.mkdir(parents=True)
    registry = output / "promotion.sqlite"
    result = {"status": "running", "freeze_sha256": freeze_hash, "published_promotion_sha256": published_hash,
              "max_consecutive_failures": FAILURE_LIMIT, "runs": {}, "decisions": {}}

    with disposable_signer() as (public_key, sign):
        controller = NotesLinkPromotion(registry, str(uuid4()), graphs, freeze_hash, published_hash, public_key,
                                        max_consecutive_failures=FAILURE_LIMIT)
        controller.initialize()
        for stage, proof in proofs.items():
            if stage == "limited" and controller.limited_route(ENVIRONMENT, eligible=True) != controller.candidate:
                raise RuntimeError("Le palier limité n'a pas été admis dans le registre.")
            controller.record_trial(stage, proof)
        promotion = controller.prepare("promote")
        signature = sign(promotion)
        controller.apply(promotion, signature)
        result["decisions"]["promote"] = {"document": promotion, "signature": signature}
        result["public_key"] = public_key
        result["promoted_active"] = controller.active()
        write_report(output, result)

        def trial(label: str, fault: str, seed: int, arm: str) -> tuple[dict, dict | None]:
            require_freeze(frozen, compile_graphs()[2])
            folder = output / label
            case = {"id": fault, "valid": fault == "valid_control", "seed": seed}

            def execute(selected: str) -> dict:
                if graphs[arm]["graph_id"] != selected:
                    raise RuntimeError(f"Le routage de {label} ne correspond pas à l'état attendu.")
                print(f"{label} {arm} graine {seed}", flush=True)
                with execution_limits(None, cpu_threads=CPU_THREADS, model_ram_mb=MODEL_RAM_MIB):
                    return run_notes(goal, catalog, runtime, folder, repair, rapidocr=True, first_diff_seed=seed,
                                     origin="link_monitor", link_candidate=arm == "candidate")

            with instrument(fault, folder, expected_diff) as observed:
                report, status = controller.run_active(execute, sign=sign)
            run_result = measure(report, observed, graphs[arm], case)
            active = controller.active()
            error_message = (report.get("error") or {}).get("message", "")
            startup_timeout = (arm == "parent" and not report["trace"] and report.get("sandbox_stopped") is True
                               and error_message.startswith("wsb start (") and "timed out" in error_message)
            result["runs"][label] = {
                "arm": arm, "case": fault, "seed": seed, "active_after": active, "measurement": run_result, "monitor": status,
            }
            if startup_timeout:
                result["runs"][label]["sandbox_start_timeout"] = True
            write_report(output, result)
            print(json.dumps({"active_after": active, "total_s": run_result["total_s"],
                              "status": run_result["workflow_status"], "monitor": status is not None}), flush=True)
            if not startup_timeout:
                if not run_result["evaluated"] or run_result["sandbox_id"] in sandbox_ids:
                    raise RuntimeError(f"La preuve de {label} ne provient pas d'un nouveau bac vérifié.")
                sandbox_ids.add(run_result["sandbox_id"])
            return run_result, status

        expected_states = (controller.candidate, controller.parent)
        for index, (fault, seed, active) in enumerate(zip(("missing_digest", "wrong_attempt"), (742, 743), expected_states), 1):
            rejected, observation = trial(f"failure_{index}", fault, seed, "candidate")
            if (not rejected["expected_behavior"] or observation is None or observation["proof"]["verified"]
                    or observation["consecutive_failures"] != index or observation["active"] != active
                    or (("rollback" in observation) != (index > FAILURE_LIMIT)) or controller.active() != active):
                raise RuntimeError(f"Le seuil ou le refus de la remise {index} n'est pas confirmé.")
        result["decisions"]["rollback"] = observation["rollback"]
        result["restored_active"] = controller.active()
        write_report(output, result)

        parent, monitoring = trial("after_rollback", "valid_control", 744, "parent")
        desktop_failure = (not parent["expected_behavior"] and parent["handoff_verdict"] == "accepted"
                           and parent["tests_passed"] == 4 and parent["sqlite_exit"] == 0
                           and parent["desktop"] and not all(parent["desktop"].values()))
        if result["runs"]["after_rollback"].get("sandbox_start_timeout") or desktop_failure:
            parent, monitoring = trial("parent_recheck", "valid_control", 744, "parent")
        if not parent["expected_behavior"] or monitoring is not None:
            raise RuntimeError("Le parcours du parent après retour arrière a échoué.")

    return finish(output, result)


def finish(output: Path, result: dict) -> dict:
    require_freeze(json.loads(LOCK_FILE.read_bytes()), compile_graphs()[2])
    if file_hash(PROMOTION_FILE) != result["published_promotion_sha256"]:
        raise RuntimeError("Les preuves publiées ont changé pendant la surveillance.")
    for packet in result["decisions"].values():
        if not verify_signature(packet["document"], packet["signature"], result["public_key"]):
            raise RuntimeError("Une signature archivée est invérifiable.")
    result["events"] = verify_chain(output / "promotion.sqlite")
    if result["events"][-4:] != ["promote", "link_observed", "link_observed", "rollback"]:
        raise RuntimeError("Les dépassements de seuil ne concordent pas avec le journal.")
    distinct = sum(run["measurement"]["evaluated"] for run in result["runs"].values())
    result.update(status="passed", signatures_reverified=True, distinct_new_sandboxes=distinct)
    write_report(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", type=Path, nargs=3, required=True, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repair = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet), model_ram_mib=MODEL_RAM_MIB)
    result = run(args.runtime.resolve(strict=True), repair, args.output.resolve())
    print(json.dumps({key: result[key] for key in ("status", "promoted_active", "restored_active", "distinct_new_sandboxes")}))


if __name__ == "__main__":
    main()
