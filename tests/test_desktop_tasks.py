from threading import Event

import pytest

from akasha_brain import desktop_tasks
from akasha_brain.notes_evolution import CANDIDATE, PARENT, set_evolution_paused


def test_graph_lays_out_dependencies_in_stable_layers():
    plan = {"steps": [
        {"id": "observe", "depends_on": []},
        {"id": "tests", "depends_on": ["observe"]},
        {"id": "sqlite", "depends_on": ["observe"]},
        {"id": "finish", "depends_on": ["tests", "sqlite"]},
    ]}
    assert [[step["id"] for step in layer] for layer in desktop_tasks.layers(plan)] == [
        ["observe"], ["tests", "sqlite"], ["finish"],
    ]
    plan["steps"][0]["depends_on"] = ["finish"]
    with pytest.raises(ValueError, match="Dépendances"):
        desktop_tasks.layers(plan)


def test_desktop_reads_counts_from_localization_and_verification_traces():
    assert desktop_tasks.test_counts({"tests": 4, "passed": 2}) == (2, 4)
    assert desktop_tasks.test_counts({"tests": [{"name": "test_persists"}], "passed": 1}) == (1, 1)
    assert desktop_tasks.test_counts({}) is None


def test_desktop_launch_exposes_stage_transitions_and_persists_history(tmp_path, monkeypatch):
    runtime = tmp_path / "python"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    runner = desktop_tasks.NotesTasks(tmp_path / "runs", runtime, None, False)
    ready, release = Event(), Event()

    def run_notes(goal, catalog, runtime, output, repair, *, rapidocr, progress):
        report = {"status": "running", "trace": [{"id": "localize", "status": "running"}]}
        progress(report)
        ready.set()
        assert release.wait(5)
        return {"status": "passed", "trace": [{"id": "localize", "status": "passed"}]}

    monkeypatch.setattr(desktop_tasks, "run_notes", run_notes)
    folder, initial = runner.start()
    try:
        assert ready.wait(5) and runner.busy
        with pytest.raises(RuntimeError, match="occupé"):
            runner.start()
        _, update = runner.updates.get_nowait()
        assert desktop_tasks.latest_steps(update)["localize"]["status"] == "running"
    finally:
        release.set()
    runner.worker.join(5)
    assert not runner.busy
    _, finished = runner.updates.get_nowait()
    assert finished["status"] == "passed"
    assert desktop_tasks.saved_tasks(runner.directory) == [(folder, finished)]
    assert initial["graph"]["goal_id"] != runner.plan["goal_id"]


def test_managed_desktop_run_keeps_the_exact_synthetic_goal_and_its_own_history(tmp_path, monkeypatch):
    runtime = tmp_path / "python"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    path = tmp_path / "journal.db"
    runner = desktop_tasks.NotesTasks(tmp_path / "runs", runtime, object(), False, evolution_db=path)
    set_evolution_paused(path, True)
    overview = runner.read_evolution()
    assert overview["active"]["graph_id"] == PARENT
    assert overview["candidate"]["graph_id"] == CANDIDATE
    assert overview["paused"]
    calls = []

    def managed(goal, catalog, runtime, output, repair, registry, budget, *, progress):
        calls.append((goal, registry))
        report = {"status": "running", "trace": []}
        progress(report)
        return {**report, "status": "passed"}

    monkeypatch.setattr(desktop_tasks, "run_managed", managed)
    first, record = runner.start()
    runner.worker.join(5)
    second, _ = runner.start()
    runner.worker.join(5)

    assert first != second and record["graph"]["goal_id"] == runner.goal["goal_id"]
    assert calls == [(runner.goal, path), (runner.goal, path)]
    assert [folder for folder, _ in desktop_tasks.saved_tasks(runner.directory)] == [second, first]
