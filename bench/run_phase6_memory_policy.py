"""Compare les politiques de mémoire autorisées sur un registre synthétique."""

import argparse
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import secrets
import shutil
from time import perf_counter, perf_counter_ns
from uuid import uuid4

from akasha_brain import memory_workflows
from akasha_brain.bounded_evolution import BoundedEvolution, Observation, Policy, SandboxScope
from akasha_brain.memory import NotesMemory
from akasha_brain.memory_policy import CONTEXTUAL, FILTERED_SIMILARITY, PolicyWorkflowLibrary
from akasha_brain.notes_evolution import GOAL_FILE, PARENT
from akasha_brain.notes_link_promotion import digest, disposable_signer
from akasha_brain.notes_sandbox import read_profile
from akasha_brain.planning import ENVIRONMENT, load_catalog
from akasha_brain.retention import load_policy
from bench.run_guided_repair import BENCH, file_hash, write_report
from bench.run_memory_reuse import ranking_cases
from bench.run_notes_link_promotion import verify_chain
from bench.run_phase5_notes_action_selection import isolated_notes_sandbox
from bench.run_phase6_skill_evolution import prepare_library

LIFECYCLE_CASES = ("desktop_erasure_pending", "code_during_desktop_erasure", "desktop_erased", "expired_objects")


def measure(library, case: str, goal: dict, catalog: dict, context, expected: str | None, scope: SandboxScope, key: str):
    started = perf_counter_ns()
    chosen = library.compare(goal, catalog, context)["gated"]
    elapsed_us = (perf_counter_ns() - started) // 1000
    result = chosen["graph"] if chosen else None
    safe = not chosen or (expected is not None and not chosen["refusals"])
    verified = result == expected
    detail = {"selected": result, "expected": expected, "verified": verified, "safe": safe, "decision_us": elapsed_us}
    return Observation(scope.sandbox_id, case, library.version, key, digest(result), safe, verified,
                       elapsed_us, elapsed_us // 1000), detail


def run(source: Path, runtime: Path, output: Path) -> dict:
    began = perf_counter()
    output.mkdir(parents=True)
    library, revoke, published = prepare_library(source, output)
    goal, catalog = json.loads(GOAL_FILE.read_bytes()), load_catalog()
    desktop_context = memory_workflows.observe(runtime, True)
    original_cases = ranking_cases(goal, catalog, desktop_context)
    code_context = next(context for name, _, _, context, _ in original_cases if name == "notes_code_nominal")
    stage = output / "input"
    stage.mkdir()
    tag = secrets.token_hex(4)
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    for name in ("probe_notes_isolation.ps1", "probe_guest_channels.ps1"):
        shutil.copyfile(BENCH / "harness" / name, stage / name)

    inputs = (Path(__file__), BENCH / "run_memory_reuse.py", Path(memory_workflows.__file__),
              BENCH.parent / "akasha_brain/memory_policy.py", BENCH.parent / "akasha_brain/bounded_evolution.py",
              BENCH.parent / "contracts/akasha_contracts/authz.py")
    hashes = {path.name: file_hash(path) for path in inputs}
    retention = load_policy()
    case_ids = tuple(case[0] for case in original_cases) + LIFECYCLE_CASES
    policy = Policy("memory", CONTEXTUAL, FILTERED_SIMILARITY,
                    digest({"sources": hashes, "library": published, "retention": retention}),
                    case_ids, ("desktop_erased", "expired_objects"), "notes_ocr_nominal", 2_000_000)
    report = {"protocol": "phase6-memory-policy-v1", "status": "running", "policy": asdict(policy),
              "library": published, "sources_sha256": hashes, "retention": retention, "sandbox": {}, "cases": {}}

    def persist():
        write_report(output, report)

    persist()
    db = output / "policy.sqlite"
    try:
        with disposable_signer() as (public_key, sign):
            controller = BoundedEvolution(db, str(uuid4()), policy, public_key)
            controller.initialize()
            with isolated_notes_sandbox(stage, tag, read_profile(), report["sandbox"], persist) as (sandbox, _):
                scope = SandboxScope(sandbox, ENVIRONMENT, "R0", True, True)
                if not controller.reserve("replay", scope):
                    raise RuntimeError("Bac de qualification mémoire non admis.")
                receipts = []

                def compare(name, request, capabilities, context, expected, memory=library.memory):
                    key = digest({"case": name, "request": request, "observed": asdict(context)})
                    rows = report["cases"][name] = {}
                    for version in (CONTEXTUAL, FILTERED_SIMILARITY):
                        ranked = PolicyWorkflowLibrary(memory, version)
                        receipt, rows[version] = measure(ranked, name, request, capabilities, context, expected, scope, key)
                        receipts.append(receipt)

                for case in original_cases:
                    compare(*case)
                library.memory.request_erasure(revoke)
                compare("desktop_erasure_pending", goal, catalog, desktop_context, None)
                compare("code_during_desktop_erasure", goal, catalog, code_context, PARENT)
                report["erasure"] = library.memory.finish_erasures()
                compare("desktop_erased", goal, catalog, desktop_context, None)
                expired_at = library.memory.clock() + timedelta(days=retention["windows_days"]["minimized_results"] + 1)
                expired = NotesMemory(library.memory.path, clock=lambda: expired_at)
                compare("expired_objects", goal, catalog, code_context, None, memory=expired)

            report["assessment"] = controller.complete_stage("replay", scope, tuple(receipts), sign)
            report["active"] = controller.select(scope, policy.limited)
            report["shadow_refused"] = not controller.reserve("shadow", scope)
        counts = {version: {
            "correct": sum(row[version]["verified"] for row in report["cases"].values()),
            "false_accepts": sum(not row[version]["safe"] for row in report["cases"].values()),
        } for version in (CONTEXTUAL, FILTERED_SIMILARITY)}
        report["counts"] = counts
        report["events"] = verify_chain(db)
        if (any(row != {"correct": len(case_ids), "false_accepts": 0} for row in counts.values())
                or report["assessment"]["qualified"] or report["active"] != CONTEXTUAL or not report["shadow_refused"]
                or "stage_rejected" not in report["events"] or "promote" in report["events"]
                or hashes != {path.name: file_hash(path) for path in inputs} or retention != load_policy()):
            raise RuntimeError("Écart de classement ou de politique mémoire.")
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
    parser.add_argument("--phase1", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.phase1.resolve(strict=True), args.runtime.resolve(strict=True), args.output.resolve())
    print(json.dumps({"status": report["status"], "active": report["active"], "counts": report["counts"]}), flush=True)


if __name__ == "__main__":
    main()
