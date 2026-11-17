"""Vérifie la préemption des simulations hors charge et le verdict Notes."""

import argparse
import json
from pathlib import Path
from statistics import quantiles
from tempfile import TemporaryDirectory
from threading import Event
from time import perf_counter, sleep
from unittest.mock import patch

from akasha_brain.desktop_jobs import DesktopJobs
from akasha_brain.desktop_tasks import NotesTasks, latest_steps, saved_task, test_counts
from akasha_brain.idle_simulation import IdleSimulations, SimulationBudget, replay_case


def race(controller, submit):
    entered, release = Event(), Event()

    def gated(case):
        entered.set()
        if not release.wait(timeout=8):
            raise RuntimeError("Le banc n’a pas produit la tâche interactive.")
        return replay_case(case)

    with patch("akasha_brain.idle_simulation.replay_case", gated):
        deadline = perf_counter() + 12
        job = controller.tick()
        while job is None and perf_counter() < deadline:
            sleep(0.2)
            job = controller.tick()
        assert job is not None and entered.wait(timeout=5)
        try:
            started = perf_counter()
            foreground = submit()
        finally:
            release.set()
        result = job.result(timeout=10)
    assert result["status"] == "preempted" and len(result["trials"]) == 1
    return started, foreground, result


def quantify(root, *, samples=20):
    baseline, preempted = [], []
    for _ in range(samples):
        jobs = DesktopJobs()
        started = perf_counter()
        baseline.append(jobs.submit(perf_counter).result(timeout=5) - started)
        controller = IdleSimulations(root, DesktopJobs(), budget=SimulationBudget(cases=4), load=lambda: 0.05)
        started, foreground, _ = race(controller, lambda: controller.scheduler.submit(perf_counter))
        preempted.append(foreground.result(timeout=5) - started)
    fixed = quantiles(baseline, n=100, method="inclusive")[94]
    with_simulation = quantiles(preempted, n=100, method="inclusive")[94]
    return {"samples": samples, "baseline_p95_ms": round(fixed * 1000, 3),
            "preemption_p95_ms": round(with_simulation * 1000, 3),
            "added_p95_ms": round((with_simulation - fixed) * 1000, 3), "maximum_added_ms": 3000}


def notes_result(tasks, folder):
    tasks.execution.result(timeout=420)
    report = saved_task(folder)
    assert report is not None and report["status"] == "passed", report
    trace = latest_steps(report)
    verification = trace["verify"]["result"]
    checks = test_counts(verification)
    assert checks == (4, 4) and verification["sqlite_verdict"] == "passed", verification
    return {"status": report["status"], "tests": list(checks), "sqlite": verification["sqlite_verdict"],
            "wall_s": report.get("wall_s"), "sandbox_stopped": report["sandbox_stopped"]}


def verify(root, runtime):
    timing = quantify(root / "timings")
    assert timing["added_p95_ms"] <= timing["maximum_added_ms"], timing
    nominal = IdleSimulations(root / "evaluation", DesktopJobs(), load=lambda: 0.05)
    evaluation = nominal.tick().result(timeout=5)
    assert evaluation["status"] == "evaluated" and len(evaluation["trials"]) == evaluation["budget"]["cases"]
    scores = {variant: sum(case["trials"][variant]["passed"] for case in evaluation["trials"])
              for variant in ("reference", "candidate")}
    base = NotesTasks(root / "baseline", runtime, None, False)
    folder, _ = base.start()
    reference = notes_result(base, folder)
    tasks = NotesTasks(root / "candidate", runtime, None, False)
    controller = IdleSimulations(tasks.directory, tasks.scheduler, budget=SimulationBudget(cases=8))
    _, (folder, _), interrupted = race(controller, tasks.start)
    notes = notes_result(tasks, folder)
    assert reference["status"] == notes["status"] and reference["sqlite"] == notes["sqlite"]
    assert reference["sandbox_stopped"] and notes["sandbox_stopped"]
    return {"status": "passed", "evaluated_cases": len(evaluation["trials"]), "scores": scores,
            "candidate": evaluation["candidate"], "timing": timing,
            "preemption": {"status": interrupted["status"], "completed_cases": len(interrupted["trials"]),
                           "host_cpu": interrupted["host_cpu"], "host_free_ram_mib": interrupted["host_free_ram_mib"]},
            "notes_baseline": reference, "notes_after_preemption": notes}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--runtime", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    with TemporaryDirectory(prefix="akasha-idle-g4-") as directory:
        result = verify(Path(directory).resolve(), args.runtime.resolve(strict=True))
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
