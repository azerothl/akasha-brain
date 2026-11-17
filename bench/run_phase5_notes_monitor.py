"""Surveille les prévisions Notes et exerce la désactivation dans un bac neuf."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
import shutil
from time import perf_counter, sleep
from unittest.mock import patch

from akasha_brain import desktop_state
from akasha_brain.notes_sandbox import read_profile
from bench.run_guided_repair import BENCH, file_hash, write_report
from bench.run_phase5_notes_action_selection import PROTOCOL, isolated_notes_sandbox, run_arm, select_plan
from bench.run_phase5_notes_desktop_state import INPUTS

PUBLISHED = BENCH / "results/phase5-notes-action-selection-v1.json"
CASE = "persist_before_restart"
LATENCY_LIMIT_US = 10_000
INJECTED_DELAY_S = 0.03
TRIALS = ("nominal", "sqlite_fault", "slow_prediction", "predictor_disabled")
EXPECTED_SQLITE_MISMATCHES = {"sqlite.row_count", "sqlite.exact_fixture_present"}


def monitor_trial(trial: dict) -> dict:
    decision = trial["decision"]
    projected = decision["projections"].get(decision["chosen"])
    comparison = None
    if projected is not None:
        expected = dict(projected["final"])
        expected.setdefault("process.pid_relation", "same")
        comparison = desktop_state.compare_notes_transition({
            "type": "DesktopStatePrediction",
            "version": desktop_state.VERSION,
            "expected": expected,
            "from_pid": trial["before"]["process"]["pid"],
        }, trial["after"])
    alerts = []
    if comparison is not None and comparison["mismatches"]:
        alerts.append("prediction_mismatch")
    if trial["decision_us"] > LATENCY_LIMIT_US:
        alerts.append("decision_latency")
    return {"comparison": comparison, "decision_us": trial["decision_us"],
            "decision_to_verdict_s": trial["decision_to_verdict_s"], "alerts": alerts}


def verify_trials(trials: dict, baseline: dict, baseline_assisted: dict) -> dict:
    nominal, faulty, slow, stopped = (trials[name] for name in TRIALS)
    monitors = [trial["monitor"] for trial in (nominal, faulty, slow, stopped)]
    good, bad, delayed, off = monitors
    return {
        "initial_states_and_admissibility_match": all(
            trial["before"]["sqlite"] == nominal["before"]["sqlite"]
            and trial["before"]["window"] == nominal["before"]["window"]
            and trial["decision"]["admissible"] == baseline["decision"]["admissible"]
            for trial in trials.values()
        ),
        "nominal_forecast_matches": nominal["success"] and good["comparison"]["status"] == "passed"
            and not good["alerts"] and nominal["decision"]["chosen"] == baseline_assisted["decision"]["chosen"],
        "sqlite_drift_alert_has_exact_variables": not faulty["success"]
            and set(bad["comparison"]["mismatches"]) == EXPECTED_SQLITE_MISMATCHES
            and bad["alerts"] == ["prediction_mismatch"],
        "latency_alert_with_valid_forecast": slow["success"] and delayed["comparison"]["status"] == "passed"
            and delayed["alerts"] == ["decision_latency"]
            and delayed["decision_us"] >= INJECTED_DELAY_S * 1_000_000,
        "predictor_invoked_only_when_enabled": all(
            trial["predictor_calls"] > 0 for trial in (nominal, faulty, slow)
        ) and stopped["predictor_calls"] == 0 and not stopped["decision"]["projections"] and off["comparison"] is None,
        "disabled_matches_published_reference": all(
            stopped["decision"][field] == baseline["decision"][field] for field in ("chosen", "steps", "admissible")
        ) and stopped["verification"] == baseline["verification"]
            and stopped["after"]["sqlite"] == baseline["after"]["sqlite"] and stopped["success"] == baseline["success"],
    }


def run(runtime: Path, output: Path) -> dict:
    began = perf_counter()
    protocol = json.loads(PROTOCOL.read_bytes())
    case, = (case for case in protocol["cases"] if case["id"] == CASE)
    published = json.loads(PUBLISHED.read_bytes())
    baselines = published["pairs"][CASE]["arms"]
    if published["status"] != "completed" or published["cases"] != protocol["cases"] or published["plans"] != protocol["plans"]:
        raise RuntimeError("Preuve de référence incompatible avec le protocole Notes.")

    output.mkdir(parents=True)
    stage = output / "input"
    stage.mkdir()
    stage_tag = secrets.token_hex(4)
    (stage / "isolation-sentinel.txt").write_text(stage_tag, encoding="ascii")
    sources = {"cases_and_policy": PROTOCOL, "reference_report": PUBLISHED,
               "monitor": Path(__file__), "predictor": Path(desktop_state.__file__),
               "selection": BENCH / "run_phase5_notes_action_selection.py",
               "sandbox_profile": BENCH / "harness/akasha-bench.wsb"}
    for name in ("probe_notes_isolation.ps1", "probe_guest_channels.ps1"):
        shutil.copyfile(BENCH / INPUTS[name], stage / name)
        sources[name] = stage / name
    for variant in ("reference", "faulty"):
        folder = stage / variant
        folder.mkdir()
        shutil.copytree(runtime, folder / "python")
        for name in ("notes_app.py", "notes_store.py", "observe_notes_desktop.py", "observe_notes_desktop.ps1"):
            source = "notes/notes_store.py" if variant == "faulty" and name == "notes_store.py" else INPUTS[name]
            shutil.copyfile(BENCH / source, folder / name)
            sources[f"{variant}/{name}"] = folder / name
    hashes = {name: file_hash(path) for name, path in sources.items()}
    report = {"protocol": "phase5-notes-monitor-v1", "status": "running", "case": case, "policy": protocol["policy"],
              "latency_threshold_us_test_only": LATENCY_LIMIT_US, "injected_delay_s": INJECTED_DELAY_S,
              "sha256": hashes, "trials": {}, "mode_events": [], "sandbox": {}}

    def persist():
        write_report(output, report)

    predictor = desktop_state.predict_notes_transition
    enabled = True
    calls = 0
    pending_delay = 0.0

    def select(plans, goal, before):
        return select_plan(plans, goal, before, use_predictor=enabled)

    def trace_predictor(before, action):
        nonlocal calls, pending_delay
        if not enabled:
            raise RuntimeError("Le prédicteur a été appelé après désactivation.")
        calls += 1
        if pending_delay:
            sleep(pending_delay)
            pending_delay = 0.0
        return predictor(before, action)

    def set_enabled(value: bool):
        nonlocal enabled
        enabled = value
        report["mode_events"].append({"predictor_enabled": enabled, "utc": datetime.now(UTC).isoformat()})
        persist()

    persist()
    try:
        with isolated_notes_sandbox(stage, stage_tag, read_profile(), report["sandbox"], persist) as (sandbox, mount):
            with patch.object(desktop_state, "predict_notes_transition", trace_predictor):
                set_enabled(True)
                for name in TRIALS:
                    if name == "predictor_disabled":
                        set_enabled(False)
                    pending_delay = INJECTED_DELAY_S if name == "slow_prediction" else 0.0
                    starting_calls = calls
                    variant = "faulty" if name == "sqlite_fault" else "reference"
                    trial = report["trials"][name] = {"predictor_enabled": enabled, "store": variant}
                    run_arm(sandbox, fr"{mount}\{variant}", case, protocol["plans"], name, trial, persist, selector=select)
                    trial["predictor_calls"] = calls - starting_calls
                    trial["monitor"] = monitor_trial(trial)
                    persist()
                    print(f"{name}: {trial['decision_us']:.1f} µs, "
                          f"appels={trial['predictor_calls']}, alertes={trial['monitor']['alerts']}", flush=True)
        report["checks"] = verify_trials(report["trials"], baselines["without_predictor"], baselines["with_predictor"])
        report["checks"]["hashed_sources_unchanged"] = hashes == {name: file_hash(path) for name, path in sources.items()}
        if not all(report["checks"].values()):
            raise RuntimeError(f"Écart dans la surveillance Notes : {report['checks']}")
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
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.runtime.resolve(strict=True), args.output.resolve())
    print(json.dumps({"status": result["status"], "wall_s": result["wall_s"]}), flush=True)


if __name__ == "__main__":
    main()
