from threading import Event
from hashlib import sha256

import pytest

from akasha_brain import desktop_tasks
from akasha_brain.notes_evolution import CANDIDATE, PARENT, set_evolution_paused
from akasha_brain.phase6_skill import verified_diff


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


def test_desktop_reads_only_the_verified_diff_of_the_selected_attempt(tmp_path):
    path = tmp_path / "result/rbitnet-1/proposal.diff"
    path.parent.mkdir(parents=True)
    content = b"--- a/notes_store.py\n+++ b/notes_store.py\n"
    path.write_bytes(content)
    result = {"diff_file": "rbitnet-1/proposal.diff", "diff_sha256": sha256(content).hexdigest(),
              "guest_sha256_verified": True}
    row = {"id": "generate_diff", "attempt": 1, "result": result}
    assert desktop_tasks.checked_task_diff(tmp_path, row) == content.decode("utf-8")
    assert desktop_tasks.checked_task_diff(tmp_path, {**row, "attempt": 2}) is None
    path.write_bytes(b"altered")
    assert desktop_tasks.checked_task_diff(tmp_path, row) is None


def test_integrated_history_reads_the_guest_verified_diff_from_staging(tmp_path):
    content = b"--- a/notes_store.py\n+++ b/notes_store.py\n"
    path = tmp_path / "input/rbitnet-1/proposal.diff"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    result = {"diff_file": "rbitnet-1/proposal.diff", "diff_sha256": sha256(content).hexdigest(),
              "guest_sha256_verified": True}
    report = {"trace": [{"id": "generate_diff", "attempt": 1, "result": result}]}

    assert verified_diff(tmp_path, report) == content
    path.write_bytes(b"altered")
    with pytest.raises(RuntimeError, match="empreinte"):
        verified_diff(tmp_path, report)
    result["guest_sha256_verified"] = False
    assert verified_diff(tmp_path, report) is None


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
        return {"status": "passed", "trace": [
            {"id": "localize", "status": "passed"},
            {"id": "prepare_reference", "capability_id": "notes.restore_reference", "status": "passed",
             "result": {"reference_sha256_verified_in_guest": True}},
        ]}

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
    runner.execution.result(timeout=5)
    assert not runner.busy
    _, finished = runner.updates.get_nowait()
    assert finished["status"] == "passed"
    solver = desktop_tasks.latest_steps(finished)["prepare_reference"]["routing"]
    assert (solver["specialist"], solver["modality"], solver["ram_mib"]) == ("notes-reference-solver", "solver", 0)
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

    def managed(goal, catalog, runtime, output, repair, registry, budget, *, progress,
                schedule_evolution, interactive):
        calls.append((goal, registry))
        report = {"status": "running", "trace": []}
        progress(report)
        return {**report, "status": "passed"}

    monkeypatch.setattr(desktop_tasks, "run_managed", managed)
    first, record = runner.start()
    runner.execution.result(timeout=5)
    second, _ = runner.start()
    runner.execution.result(timeout=5)

    assert first != second and record["graph"]["goal_id"] == runner.goal["goal_id"]
    assert calls == [(runner.goal, path), (runner.goal, path)]
    assert [folder for folder, _ in desktop_tasks.saved_tasks(runner.directory)] == [second, first]
