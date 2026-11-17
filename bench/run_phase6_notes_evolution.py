"""Cycle de promotion, surveillance et repli de la route Notes dans Windows Sandbox."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import secrets
import shutil
from time import perf_counter
from uuid import uuid4

from akasha_brain.bounded_evolution import BoundedEvolution, Observation, Policy, SandboxScope, STAGES
from akasha_brain.notes_link_promotion import digest, disposable_signer, verify_signature
from akasha_brain.notes_sandbox import read_profile
from akasha_brain.planning import ENVIRONMENT
from bench.run_guided_repair import BENCH, file_hash, write_report
from bench.run_notes_link_promotion import verify_chain
from bench.run_phase5_notes_action_selection import PROTOCOL, isolated_notes_sandbox, run_arm
from bench.run_phase5_notes_desktop_state import INPUTS
from bench.run_phase5_notes_monitor import CASE, LATENCY_LIMIT_US, PUBLISHED, monitor_trial

PARENT, CANDIDATE = "without_predictor", "with_predictor"
REPLAY = (CASE, "persist_new_note")
SHADOW = ("restart_with_durable_note", "verify_existing_note", "restart_empty_notes")
APPROVED_PLANS = {"inspect": [], "save": ["save"], "restart": ["restart"], "save_then_restart": ["save", "restart"]}


def stage_bench(stage: Path, runtime: Path) -> dict[str, Path]:
    stage.mkdir()
    inputs = {
        "case_protocol": PROTOCOL,
        "implementation": BENCH.parent / "akasha_brain/bounded_evolution.py",
        "runner": Path(__file__),
        "selection": BENCH / "run_phase5_notes_action_selection.py",
        "monitor": BENCH / "run_phase5_notes_monitor.py",
        "predictor": BENCH.parent / "akasha_brain/desktop_state.py",
        "permissions": BENCH.parent / "contracts/akasha_contracts/authz.py",
        "reference": PUBLISHED,
        "sandbox_profile": BENCH / "harness/akasha-bench.wsb",
    }
    for name in ("probe_notes_isolation.ps1", "probe_guest_channels.ps1"):
        shutil.copyfile(BENCH / INPUTS[name], stage / name)
        inputs[name] = stage / name
    for variant in ("reference", "faulty"):
        root = stage / variant
        root.mkdir()
        shutil.copytree(runtime, root / "python")
        inputs[f"{variant}/python.exe"] = root / "python/python.exe"
        for name in ("notes_app.py", "notes_store.py", "observe_notes_desktop.py", "observe_notes_desktop.ps1"):
            source = "notes/notes_store.py" if variant == "faulty" and name == "notes_store.py" else INPUTS[name]
            shutil.copyfile(BENCH / source, root / name)
            inputs[f"{variant}/{name}"] = root / name
    return inputs


def observe_trial(sandbox: str, case: dict, version: str, trial: dict) -> Observation:
    signals = trial["verification"]
    monitored = monitor_trial(trial)
    comparison = monitored["comparison"]
    before = trial["before"]
    comparable = {"case": case["id"], "goal": case["goal"], "window": before["window"], "sqlite": before["sqlite"],
                  "process_alive": before["process"]["alive"], "admissible": trial["decision"]["admissible"]}
    return Observation(sandbox, case["id"], version, digest(comparable), digest(trial),
                       trial["closed"] and all(signals[name] for name in ("live", "window", "foreground",
                                                                        "uia_focus", "pid_relation", "integrity")),
                       trial["success"], round(trial["decision_us"]), round(trial["decision_to_verdict_s"] * 1000),
                       tuple(comparison["mismatches"]) if comparison is not None else ())


def run(runtime: Path, output: Path) -> dict:
    started = perf_counter()
    output.mkdir(parents=True)
    stage = output / "input"
    inputs = stage_bench(stage, runtime)
    hashes = {name: file_hash(path) for name, path in inputs.items()}
    protocol = json.loads(PROTOCOL.read_bytes())
    if protocol["plans"] != APPROVED_PLANS or list(protocol["plans"]) != list(APPROVED_PLANS):
        raise RuntimeError("Catalogue de plans hors du périmètre R0/R1 contrôlé.")
    cases = {case["id"]: case for case in protocol["cases"]}
    previous = json.loads(PUBLISHED.read_bytes())
    if previous["status"] != "completed" or previous["cases"] != protocol["cases"] or previous["plans"] != protocol["plans"]:
        raise RuntimeError("Référence publiée incompatible.")
    archived = previous["pairs"][CASE]["arms"][PARENT]
    policy = Policy("route", PARENT, CANDIDATE, digest(hashes), REPLAY, SHADOW, CASE, LATENCY_LIMIT_US)
    tag, profile = secrets.token_hex(4), read_profile()
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    report = {"protocol": "phase6-notes-evolution-v1", "status": "running", "policy": asdict(policy),
              "inputs_sha256": hashes, "stages": {}, "live": {}, "controls": {}}

    def persist():
        write_report(output, report)

    def trial(sandbox, mount, case_id, version, evidence, store="reference"):
        run_arm(sandbox, fr"{mount}\{store}", cases[case_id], protocol["plans"], version, evidence, persist)
        return observe_trial(sandbox, cases[case_id], version, evidence)

    persist()
    db = output / "evolution.sqlite"
    try:
        with disposable_signer() as (public_key, sign):
            controller = BoundedEvolution(db, str(uuid4()), policy, public_key)
            controller.initialize()
            report["public_key"] = public_key
            for step in STAGES:
                evidence = report["stages"][step] = {"sandbox": {}, "trials": {}}
                receipts = []
                with isolated_notes_sandbox(stage, tag, profile, evidence["sandbox"], persist) as (sandbox, mount):
                    scope = SandboxScope(sandbox, ENVIRONMENT, "R1", True, True)
                    if step == "replay":
                        denied = {
                            "risk_r2": replace(scope, risk_class="R2"),
                            "risk_r3": replace(scope, risk_class="R3"),
                            "unverified_confinement": replace(scope, confinement_verified=False),
                            "real_data": replace(scope, synthetic=False),
                        }
                        for name, changed in denied.items():
                            report["controls"][name] = not controller.reserve(step, changed)
                        report["controls"]["out_of_order"] = not controller.reserve("limited", scope)
                    if not controller.reserve(step, scope) or controller.active() != PARENT:
                        raise RuntimeError(f"Admission inattendue au palier {step}.")
                    if step == "limited":
                        report["controls"]["second_limited_refused"] = not controller.reserve(step, scope)
                    for case_id in policy.cases(step):
                        arms = (CANDIDATE,) if step == "limited" else cases[case_id]["order"]
                        pair = evidence["trials"][case_id] = {}
                        for version in arms:
                            pair[version] = {}
                            receipts.append(trial(sandbox, mount, case_id, version, pair[version]))
                evidence["assessment"] = controller.complete_stage(step, scope, tuple(receipts), sign)
                evidence["active_after"] = controller.active()
                persist()
                if not evidence["assessment"]["qualified"] or evidence["active_after"] != (
                        CANDIDATE if step == "limited" else PARENT):
                    raise RuntimeError(f"Qualification ou sélection inattendue au palier {step}.")
                print(f"{step}: qualifié, route active {evidence['active_after']}", flush=True)

            live = report["live"] = {"sandbox": {}, "trials": {}}
            with isolated_notes_sandbox(stage, tag, profile, live["sandbox"], persist) as (sandbox, mount):
                scope = SandboxScope(sandbox, ENVIRONMENT, "R1", True, True)
                report["controls"]["outside_qualified_case_uses_parent"] = (
                    controller.select(scope, "restart_empty_notes") == PARENT
                )
                for name, store, expected in (("nominal", "reference", CANDIDATE),
                                               ("drift", "faulty", CANDIDATE),
                                               ("after_rollback", "reference", PARENT)):
                    selected = controller.select(scope, CASE)
                    if selected != expected:
                        raise RuntimeError(f"Route inattendue pour {name}.")
                    evidence = live["trials"][name] = {"selected": selected, "store": store}
                    receipt = trial(sandbox, mount, CASE, selected, evidence, store)
                    evidence["observation"] = controller.observe(scope, receipt, sign)
                    evidence["mismatches"] = list(receipt.mismatches)
                    persist()
        nominal, drift, after = (report["live"]["trials"][name] for name in ("nominal", "drift", "after_rollback"))
        promoted = report["stages"]["limited"]["assessment"]["decision"]
        reverted = drift["observation"]["decision"]
        report["checks"] = {
            "controls_pass": all(report["controls"].values()),
            "nominal_pass": nominal["success"] and not nominal["observation"]["alerts"],
            "drift_reports_sqlite_and_reverts": set(drift["mismatches"]) == {
                "sqlite.row_count", "sqlite.exact_fixture_present",
            } and drift["observation"]["active"] == PARENT,
            "reference_restored": controller.active() == PARENT and after["decision"] == archived["decision"]
                and after["verification"] == archived["verification"],
            "signed_decisions": all(verify_signature(item["document"], item["signature"], public_key)
                                    for item in (promoted, reverted)),
            "inputs_unchanged": hashes == {name: file_hash(path) for name, path in inputs.items()},
        }
        report["events"] = verify_chain(db)
        if not all(report["checks"].values()) or report["events"].count("promote") != 1 or report["events"].count("rollback") != 1:
            raise RuntimeError(f"Cycle intégré incomplet : {report['checks']}")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["wall_s"] = round(perf_counter() - started, 3)
        persist()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.runtime.resolve(strict=True), args.output.resolve())
    print(json.dumps({"status": result["status"], "wall_s": result["wall_s"], "checks": result["checks"]}), flush=True)


if __name__ == "__main__":
    main()
