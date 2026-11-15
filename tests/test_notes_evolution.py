import json
from pathlib import Path
from threading import get_ident
from uuid import uuid4

import pytest

from akasha_brain import notes_evolution
from akasha_brain.experience import record_experience, transaction
from akasha_brain.notes_evolution import (
    CANDIDATE, GOAL_FILE, PARENT, STAGES, EvolutionBudget, evolve, evolution_status, initialize, lease, rollback,
    run_managed,
)
from akasha_brain.planning import PlanningError, compile_goal, load_catalog
from contracts.akasha_contracts.validate import validate


def report_for(plan, *, passed=True):
    results = {
        "generate_diff": {"diff_applied": True, "git_apply_check": True, "guest_sha256_verified": True,
                          "diff_sha256": "demo", "prompt": "private prompt"},
        "verify": {"passed": 4, "pytest_exit": 0, "sqlite_verifier_exit": 0},
        "verify_desktop": {"guest_exit_code": 0x471F},
    }
    results["generate_diff"]["matches_desktop_protocol"] = plan["graph_id"] == CANDIDATE
    return {
        "graph": plan, "status": "passed" if passed else "failed", "sandbox_id": str(uuid4()),
        "sandbox_stopped": True, "isolation": {"guest_write_to_input_denied": True},
        "accepted_attempt": 1, "wall_s": 1.0,
        "trace": [{**step, "status": "passed", "authorization": "allowed", "wall_s": 0.2,
                   "result": results.get(step["id"], {})} for step in plan["steps"]],
    }


@pytest.mark.parametrize("budget,first_ok,stages,status", [
    (EvolutionBudget(30, 3, 2, 8192), True, STAGES, "promoted"),
    (EvolutionBudget(30, 2, 2, 8192), True, (), "waiting"),
    (EvolutionBudget(0, 3, 2, 8192), True, (), "waiting"),
    (EvolutionBudget(30, 3, 2, 8192), False, ("replay",), "retained"),
])
def test_managed_task_triggers_a_bounded_worker_without_recursion(tmp_path, monkeypatch, budget, first_ok, stages, status):
    catalog = load_catalog()
    goal = json.loads(GOAL_FILE.read_text(encoding="utf-8"))
    path = tmp_path / "journal.db"
    task_thread = get_ident()
    calls = []

    def fake_run(goal, catalog, runtime, output, repair, *, first_diff_seed, rapidocr, experience_db, origin="task"):
        calls.append((origin, rapidocr, get_ident()))
        output.mkdir(parents=True)
        report = report_for(compile_goal(goal, catalog, rbitnet=True, rapidocr=rapidocr),
                            passed=origin != "task" or first_ok)
        report["experience_record_id"] = record_experience(experience_db, report, origin)
        return report

    monkeypatch.setattr(notes_evolution, "run_notes", fake_run)
    task = run_managed(goal, catalog, Path("python"), tmp_path / "task", object(), path, budget)
    assert task["evolution"]["status"] == status
    assert calls[0] == ("task", False, task_thread)
    assert [(origin, rapidocr) for origin, rapidocr, _ in calls[1:]] == [(stage, True) for stage in stages]
    assert all(thread != task_thread for _, _, thread in calls[1:])

    state = evolution_status(path)
    events = [item["entry"]["event"] for item in state["events"]]
    assert events.count("triggered") == 1
    assert events.count("trial_started") == len(stages)
    assert state["active"] == (CANDIDATE if status == "promoted" else PARENT)
    with transaction(path) as db:
        records = db.execute("SELECT record FROM experiences").fetchall()
    assert len(records) == len(calls)
    for (raw,) in records:
        assert "private prompt" not in raw
        record = json.loads(raw)
        assert validate(record, "ExperienceRecord") == []
        assert record["contains_user_content"] is False
    if status == "promoted":
        assert rollback(path) == {"previous_active": CANDIDATE, "active": PARENT}
        assert evolution_status(path)["events"][-1]["entry"]["event"] == "rolled_back"


def test_notes_registry_lease_prevents_concurrent_trials(tmp_path):
    path = tmp_path / "journal.db"
    with lease(path), pytest.raises(PlanningError, match="déjà une exécution"):
        with lease(path):
            pytest.fail("Le second lanceur a obtenu le bail.")
    with lease(path):
        pass


@pytest.mark.parametrize("failure,reason", [
    ("missing_sqlite", "insufficient_evidence"),
    ("timeout", "resource_budget_exceeded"),
    ("memory", "resource_budget_exceeded"),
])
def test_evolution_retains_parent_after_a_failed_promotion_gate(tmp_path, monkeypatch, failure, reason):
    catalog = load_catalog()
    path = tmp_path / "journal.db"
    goal = initialize(path, catalog)
    reference = report_for(compile_goal(goal, catalog, rbitnet=True))
    reference["experience_record_id"] = record_experience(path, reference, "task")
    clock = [100]
    monkeypatch.setattr(notes_evolution, "monotonic", lambda: clock[0])

    def trial(stage):
        assert stage == "replay"
        result = report_for(compile_goal(goal, catalog, rbitnet=True, rapidocr=True))
        if failure == "timeout":
            clock[0] += 30
        elif failure == "memory":
            result.update(status="failed", error={"code": "resource_budget_exceeded", "family": "ressource"})
        else:
            result["trace"][-1]["result"]["guest_exit_code"] = 0x470F
        result["experience_record_id"] = record_experience(path, result, stage)
        return result

    result = evolve(path, "test", EvolutionBudget(30, 3, 2, 8192), reference, trial)
    assert result["reason"] == reason
    assert evolution_status(path)["active"] == PARENT
