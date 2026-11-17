from threading import Event

from akasha_brain import idle_simulation
from akasha_brain.desktop_jobs import DesktopJobs
from akasha_brain.idle_simulation import IdleSimulations, SimulationBudget, replay_case, synthetic_cases


def test_synthetic_cases_preserve_independent_outcomes():
    cases = list(synthetic_cases(23, 8))
    assert cases == list(synthetic_cases(23, 8))
    results = [replay_case(case) for case in cases]
    for case, result in zip(cases, results, strict=True):
        assert result["case"].startswith("sim-notes-")
        assert result["trials"]["candidate"]["passed"] is (case["saved"] or not case["faulty"])
    assert any(result["trials"]["candidate"]["passed"] and not result["trials"]["reference"]["passed"]
               for result in results)


def test_simulation_requires_budget_and_idle_slot(tmp_path, monkeypatch):
    jobs = DesktopJobs()
    monkeypatch.setattr(idle_simulation, "available_ram", lambda: 255)
    options = SimulationBudget(cases=2)
    controller = IdleSimulations(tmp_path, jobs, budget=options, load=lambda: 0.10)
    assert controller.tick() is None
    monkeypatch.setattr(idle_simulation, "available_ram", lambda: 4096)
    controller.load = lambda: 0.8
    assert controller.tick() is None
    controller.load = lambda: 0.10
    release = Event()
    foreground = jobs.submit(lambda: release.wait(timeout=5))
    try:
        assert controller.tick() is None
    finally:
        release.set()
    assert foreground.result(timeout=5)


def test_simulation_yields_at_the_next_checkpoint(tmp_path, monkeypatch):
    jobs = DesktopJobs()
    entered, release = Event(), Event()
    monkeypatch.setattr(idle_simulation, "available_ram", lambda: 4096)

    def gated(case):
        entered.set()
        assert release.wait(timeout=5)
        return replay_case(case)

    monkeypatch.setattr(idle_simulation, "replay_case", gated)
    controller = IdleSimulations(tmp_path, jobs, budget=SimulationBudget(cases=4), load=lambda: 0.10)
    background = controller.tick()
    assert entered.wait(timeout=5)
    foreground = jobs.submit(lambda: "interactive")
    release.set()
    report = background.result(timeout=5)
    assert foreground.result(timeout=5) == "interactive"
    assert report["status"] == "preempted" and len(report["trials"]) == 1
    assert len(list((tmp_path / "idle-simulations").glob("*/report.json"))) == 1
