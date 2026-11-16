import json
from pathlib import Path
from threading import Event, get_ident
from uuid import uuid4

import pytest

from akasha_brain import desktop_tasks, notes_evolution
from akasha_brain.evolution_consent import ReuseScope, grant, revoke
from akasha_brain.experience import record_experience, transaction
from akasha_brain.notes_evolution import (
    CANDIDATE, GOAL_FILE, PARENT, STAGES, SYNTHETIC_REFERENCE, EvolutionBudget, evolve, evolution_overview, evolution_status,
    initialize, lease, rollback, run_managed, set_evolution_paused,
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


@pytest.mark.parametrize("pause_before,expires", [("shadow", False), ("promotion", False), ("replay", True)])
def test_pause_at_safe_point_and_resume_same_cycle(tmp_path, monkeypatch, pause_before, expires):
    path = tmp_path / "journal.db"
    catalog = load_catalog()
    goal = initialize(path, catalog)
    parent = compile_goal(goal, catalog, rbitnet=True)
    candidate = compile_goal(goal, catalog, rbitnet=True, rapidocr=True)
    reference = {**report_for(parent), "experience_record_id": str(uuid4())}
    clock = [100.0]
    stages = []
    pauses = []
    before = (*STAGES, "promotion")

    def trial(stage):
        stages.append(stage)
        if before[len(stages)] == pause_before:
            set_evolution_paused(path, True)
        return {**report_for(candidate), "experience_record_id": str(uuid4())}

    def wait(seconds):
        state = evolution_overview(path)
        assert state["active"] == parent and state["candidate"] == candidate
        assert state["paused"]
        event = state["latest"]
        assert event["event"] == "pause_reached"
        assert event["cycle_id"] == "cycle"
        assert event["details"] == {"before": pause_before}
        assert tuple(stages) == STAGES[:before.index(pause_before)]
        pauses.append(event)
        clock[0] += seconds if not expires else 30
        if not expires:
            set_evolution_paused(path, False)

    monkeypatch.setattr(notes_evolution, "monotonic", lambda: clock[0])
    monkeypatch.setattr(notes_evolution, "sleep", wait)
    if pause_before == "replay":
        set_evolution_paused(path, True)
        initialize(path, catalog)
    with lease(path):
        result = evolve(path, "cycle", EvolutionBudget(30, 3, 2, 8192), reference, trial)
    assert len(pauses) == 1
    if expires:
        assert result["reason"] == "resource_budget_exceeded"
        assert not stages and evolution_overview(path)["paused"]
    else:
        assert result["status"] == "promoted" and tuple(stages) == STAGES
        state = evolution_overview(path)
        assert state["active"] == candidate and state["candidate"] is None
        assert not state["paused"] and state["can_rollback"]
        rollback(path)
        assert evolution_overview(path)["active"] == parent
        assert evolution_overview(path)["candidate"] == candidate


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


@pytest.mark.parametrize("revoke_at,expected_stages", [
    ("pending", ()), ("running", ("replay",)), ("promotion", STAGES),
])
def test_revocation_blocks_reuse_at_safe_points(tmp_path, monkeypatch, revoke_at, expected_stages):
    catalog = load_catalog()
    path = tmp_path / "journal.db"
    goal = initialize(path, catalog)
    consent_id = grant(path, "project-a", ["source_code"])["consent_id"]
    scope = ReuseScope("project-a", "source_code", consent_id, "project", False)
    reference = report_for(compile_goal(goal, catalog, rbitnet=True))
    reference["experience_record_id"] = record_experience(path, reference, "task")
    stages = []
    last_finished = False
    audit = notes_evolution.audit

    def observe_audit(db, cycle, event, details):
        nonlocal last_finished
        audit(db, cycle, event, details)
        if event == "trial_finished" and details["stage"] == STAGES[-1]:
            last_finished = True

    def clock():
        nonlocal last_finished
        if revoke_at == "promotion" and last_finished:
            last_finished = False
            revoke(path, consent_id)
        return 100

    def trial(stage):
        stages.append(stage)
        if revoke_at == "running":
            revoke(path, consent_id)
        result = report_for(compile_goal(goal, catalog, rbitnet=True, rapidocr=True))
        result["experience_record_id"] = record_experience(path, result, stage)
        return result

    monkeypatch.setattr(notes_evolution, "audit", observe_audit)
    monkeypatch.setattr(notes_evolution, "monotonic", clock)
    if revoke_at == "pending":
        revoke(path, consent_id)
    result = evolve(path, "test", EvolutionBudget(30, 3, 2, 8192), reference, trial, reuse=(scope,))
    assert result["status"] == "retained"
    assert result["reason"] == "consent_revoked"
    assert tuple(stages) == expected_stages
    state = evolution_status(path)
    assert state["active"] == PARENT
    assert all(item["entry"]["event"] != "activated" for item in state["events"])


def test_desktop_runs_queued_tasks_between_trials_in_fifo_order(tmp_path, monkeypatch):
    runtime = tmp_path / "python"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    path = tmp_path / "journal.db"
    runner = desktop_tasks.NotesTasks(tmp_path / "runs", runtime, object(), False, evolution_db=path)
    ready, release = Event(), Event()
    calls = []

    def run_notes(goal, catalog, runtime, output, repair, *, first_diff_seed, rapidocr, experience_db,
                  origin="task", progress=None):
        calls.append(origin)
        if origin == "replay":
            ready.set()
            assert release.wait(5)
        output.mkdir(parents=True)
        plan = compile_goal(goal, catalog, rbitnet=True, rapidocr=rapidocr)
        report = report_for(plan)
        report["experience_record_id"] = record_experience(experience_db, report, origin)
        return report

    monkeypatch.setattr(notes_evolution, "run_notes", run_notes)
    original, _ = runner.start()
    try:
        assert ready.wait(5) and not runner.busy
        project = runner.scheduler.submit(lambda: calls.append("project"))
        interactive, record = runner.start()
        assert record["status"] == "waiting" and runner.busy
        assert calls == ["task", "replay"]
    finally:
        release.set()
    project.result(timeout=5)
    runner.execution.result(timeout=5)
    runner.scheduler.submit(lambda: None, background=True).result(timeout=5)
    assert calls == ["task", "replay", "project", "task", "shadow", "limited"]
    assert (original / "result" / "report.json").is_file()
    assert [folder for folder, _ in desktop_tasks.saved_tasks(runner.directory)] == [interactive, original]
    events = [row["entry"] for row in evolution_status(path)["events"]]
    priority = [event for event in events if event["event"] == "interactive_priority"]
    assert [event["details"] for event in priority] == [{"before": "shadow"}]
    assert evolution_status(path)["active"] == CANDIDATE


@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_completed_project_starts_only_the_synthetic_cycle(tmp_path, monkeypatch, outcome):
    runtime = tmp_path / "python"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    registry = tmp_path / "notes.db"
    runner = desktop_tasks.NotesTasks(tmp_path / "runs", runtime, object(), False, evolution_db=registry)
    calls = []
    private_data = "PROJECT_DATA_NOT_ELIGIBLE_FOR_REUSE"

    def project_task():
        calls.append("project-" + outcome)
        if outcome == "failed":
            raise RuntimeError(private_data)
        return {"status": "awaiting_approval", "proposal": private_data}

    def run_notes(goal, catalog, runtime, output, repair, *, first_diff_seed, rapidocr, experience_db, origin):
        assert goal == runner.goal and experience_db == registry
        assert output.is_relative_to(runner.directory / "evolution")
        assert rapidocr is (origin != SYNTHETIC_REFERENCE)
        calls.append(origin)
        output.mkdir(parents=True)
        report = report_for(compile_goal(goal, catalog, rbitnet=True, rapidocr=rapidocr))
        report["experience_record_id"] = record_experience(experience_db, report, origin)
        return report

    monkeypatch.setattr(notes_evolution, "run_notes", run_notes)
    project = runner.submit_project(project_task)
    if outcome == "failed":
        with pytest.raises(RuntimeError, match=private_data):
            project.result(timeout=5)
    else:
        assert project.result(timeout=5)["proposal"] == private_data
    runner.scheduler.submit(lambda: None, background=True).result(timeout=5)
    assert calls == ["project-" + outcome, SYNTHETIC_REFERENCE, *STAGES]
    state = evolution_status(registry)
    assert state["active"] == CANDIDATE
    triggers = [row["entry"]["details"] for row in state["events"] if row["entry"]["event"] == "triggered"]
    assert len(triggers) == 1 and triggers[0]["outcome"] == outcome and triggers[0]["source"] == "synthetic"
    assert private_data not in json.dumps(state)
