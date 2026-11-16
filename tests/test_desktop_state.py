import json

from akasha_brain.desktop_state import compare_notes_transition, decode_notes_observation, predict_notes_transition
from bench import run_phase5_notes_desktop_state as runner


def test_notes_predictions_are_written_before_guest_actions(tmp_path, monkeypatch):
    path = tmp_path / "report.json"

    def guest_exit(sandbox_id, command):
        assert sandbox_id == "sandbox"
        if command == "probe -Mode begin":
            assert not path.exists()
            return 0x6000051F
        saved = json.loads(path.read_bytes())
        if command == "probe -Mode save -NotesId 5":
            assert saved["transitions"]["save"]["prediction"]["expected"]["sqlite.row_count"] == 1
            assert "after_save" not in saved["observations"]
            return 0x6000053F
        assert command == "probe -Mode restart -NotesId 5"
        assert saved["transitions"]["save"]["comparison"]["status"] == "passed"
        forecast = saved["transitions"]["restart"]["prediction"]
        assert forecast["from_observation_window"] == saved["observations"]["after_save"]["observation_window"]
        assert forecast["expected"]["process.pid_relation"] == "different"
        assert forecast["expected"]["sqlite.exact_fixture_present"] is True
        assert "after_restart" not in saved["observations"]
        return 0x6000063F

    monkeypatch.setattr(runner, "guest_exit", guest_exit)
    report = {"observations": {}}
    runner.run_transitions("sandbox", "probe", tmp_path, report)
    assert [transition["comparison"]["matched"] for transition in report["transitions"].values()] == [9, 9]


def test_notes_comparison_detects_pid_focus_and_sqlite_mismatches():
    def observation(packet):
        return decode_notes_observation(
            packet, started_at="2026-11-16T12:00:00+00:00", finished_at="2026-11-16T12:00:01+00:00",
        )

    forecast = predict_notes_transition(observation(0x6000053F), "restart")
    result = compare_notes_transition(forecast, observation(0x6000050F))
    assert result["status"] == "failed"
    assert result["matched"] == 5
    assert set(result["mismatches"]) == {
        "process.pid_relation", "window.uia_focus_owned_by_process", "sqlite.row_count", "sqlite.exact_fixture_present",
    }
