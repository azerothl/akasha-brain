import pytest

from akasha_brain import notes_runtime
from akasha_brain.notes_runtime import TESTS, authorization_controls, decode_validation


def test_notes_execution_requires_scope_and_verified_confinement():
    step = {"id": "localize", "action": "observe"}
    goal = {"risk_class": "R1", "constraints": {"allowed_actions": ["observe"]}}
    assert authorization_controls(step, goal) == {
        "missing_confinement": "permission_denied",
        "out_of_scope": "permission_denied",
    }


def test_decode_notes_results_preserves_each_test_and_verifier_status():
    code = 0x50000000 | (1 << 10) | (2 << 12) | (3 << 14) | (1 << 4) | 1
    report = decode_validation(code)
    assert [(test["name"], test["status"]) for test in report["tests"]] == list(zip(
        TESTS, ("passed", "failed", "error", "skipped"),
    ))
    assert report["passed"] == report["pytest_exit"] == report["sqlite_verifier_exit"] == 1
    assert report["sqlite_verdict"] == "failed"


def test_decode_notes_results_rejects_a_plain_or_unknown_guest_exit():
    with pytest.raises(RuntimeError):
        decode_validation(37)


@pytest.mark.parametrize("change", [
    ("<Networking>Disable</Networking>", "<Networking>Enable</Networking>"),
    ("<MappedFolders />", "<MappedFolders><MappedFolder /></MappedFolders>"),
])
def test_notes_profile_refuses_an_open_channel_or_an_unexpected_mount(tmp_path, monkeypatch, change):
    profile = notes_runtime.read_profile()
    assert change[0] in profile
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "akasha-bench.wsb").write_text(profile.replace(*change), encoding="utf-8")
    monkeypatch.setattr(notes_runtime, "BENCH", tmp_path)
    with pytest.raises(RuntimeError):
        notes_runtime.read_profile()
