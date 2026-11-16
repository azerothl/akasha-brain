import json

import pytest

from akasha_brain import tasks_routing as routing
from bench.run_phase4_tasks_baseline import FIXTURES, prepare_case


@pytest.fixture
def task(tmp_path):
    case = json.loads((FIXTURES / "cases.json").read_bytes())["cases"][0]
    contract = json.loads((FIXTURES / "coverage-v2.json").read_bytes())["cases"][case["id"]]
    directory = tmp_path / "case"
    prepare_case(case, directory)
    goal = json.loads((directory / "goal.json").read_bytes())
    return directory, goal, routing.bind_contract(directory, case["target"], contract["plan"])


def test_only_active_qualified_specialist_routes_and_retirement_is_durable(tmp_path, task):
    directory, goal, contract = task
    path = tmp_path / "routing.sqlite"
    registry = routing.Registry(path)
    assert registry.initialize()["state"] == "candidate"
    assert registry.admit(goal, directory, contract)["graph"] == routing.REFERENCE
    assert registry.transition("activate")["state"] == "active"
    assert registry.admit(goal, directory, contract)["graph"] == routing.SPECIALIST
    assert registry.admit(goal, directory, None)["reason"] == "coverage_unavailable"
    assert registry.transition("deprecate")["state"] == "deprecated"
    assert registry.admit(goal, directory, contract)["graph"] == routing.REFERENCE
    assert registry.transition("retire")["state"] == "retired"
    reopened = routing.Registry(path)
    assert reopened.admit(goal, directory, contract) == {
        "graph": routing.REFERENCE, "reason": "retired", "state": "retired",
    }
    with pytest.raises(RuntimeError, match="Transition"):
        reopened.transition("activate")


def test_case_drift_and_unverified_specialist_fall_back(tmp_path, task, monkeypatch):
    directory, goal, contract = task
    registry = routing.Registry(tmp_path / "routing.sqlite")
    registry.initialize()
    registry.transition("activate")
    assert registry.admit(goal, directory, {**contract, "goal_id": "different"})["graph"] == routing.REFERENCE
    (directory / "schema.sql").write_text("ATTACH DATABASE 'outside.db' AS external", encoding="utf-8")
    rebound = routing.bind_contract(directory, contract["target"], contract["plan"])
    assert registry.admit(goal, directory, rebound)["reason"] == "coverage_unavailable"
    monkeypatch.setattr(routing, "qualification", lambda: {})
    assert registry.admit(goal, directory, contract)["reason"] == "qualification_unavailable"


def test_other_families_do_not_read_or_create_a_tasks_registry(tmp_path):
    path = tmp_path / "absent.sqlite"
    registry = routing.Registry(path)
    for goal in ({"inputs": ["bench://notes"]}, {"inputs": ["project://test"]}, {"inputs": ["bench://communication"]}):
        assert registry.admit(goal, tmp_path, None) == {"graph": None, "reason": "outside_tasks"}
    assert not path.exists()


def test_initialization_cannot_reuse_a_different_registry(tmp_path):
    path = tmp_path / "existing.sqlite"
    path.write_bytes(b"existing content")
    with pytest.raises(FileExistsError):
        routing.Registry(path).initialize()
    assert path.read_bytes() == b"existing content"
