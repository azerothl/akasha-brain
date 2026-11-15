import json
from pathlib import Path

import pytest

from akasha_brain.planning import PlanningError, compile_goal, load_catalog
from contracts.akasha_contracts.errors import ErrorCode


@pytest.fixture
def goal():
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "contracts/examples/goal_notes_regression.json").read_text(encoding="utf-8"))


def test_compile_notes_baseline_pins_capabilities_and_validation(goal):
    catalog = load_catalog()
    graph = compile_goal(goal, catalog)
    assert graph["graph_version"] == "1.0.0"
    assert graph["sandbox_tier"] == "windows-sandbox"
    assert [(step["id"], step["version"], step["depends_on"]) for step in graph["steps"]] == [
        ("localize", "1.0.0", []),
        ("prepare_reference", "1.0.0", ["localize"]),
        ("verify", "1.0.0", ["prepare_reference"]),
    ]
    assert graph["expected_validation"] == {"tests_passed": 4, "verifier": "sqlite_persistence"}
    assert all(step["capability_id"] != "notes.form_ocr" for step in graph["steps"])


@pytest.mark.parametrize("override,error", [
    ({"inputs": ["bench://tasks"]}, ErrorCode.CAPABILITY_UNAVAILABLE),
    ({"risk_class": "R3"}, ErrorCode.PERMISSION_DENIED),
    ({"constraints": {"environment_id": "bench-notes", "allowed_actions": ["observe", "test"]}},
     ErrorCode.PERMISSION_DENIED),
    ({"approval_requirements": ["user"]}, ErrorCode.APPROVAL_REQUIRED),
    ({"success_conditions": [{"predicate": "test_suite_passes", "on": "CodeState",
                              "args": {"command": "other command"}}]},
     ErrorCode.CAPABILITY_UNAVAILABLE),
])
def test_rejects_goals_outside_the_evaluated_path(goal, override, error):
    with pytest.raises(PlanningError) as denied:
        compile_goal({**goal, **override}, load_catalog())
    assert denied.value.error.code == error


def test_declared_but_unevaluated_capability_cannot_be_compiled(goal):
    catalog = load_catalog()
    del catalog["notes.verify", "1.0.0"]["evaluation"]
    with pytest.raises(PlanningError) as denied:
        compile_goal(goal, catalog)
    assert denied.value.error.code == ErrorCode.CAPABILITY_UNAVAILABLE


def test_rbitnet_replaces_only_the_repair_step(goal):
    plan = compile_goal(goal, load_catalog(), rbitnet=True)
    assert plan["graph_id"] == "notes-rbitnet"
    assert [step["id"] for step in plan["steps"]] == ["localize", "generate_diff", "verify"]
    assert plan["steps"][1]["capability_id"] == "notes.repair_rbitnet"
    assert plan["steps"][2]["depends_on"] == ["generate_diff"]


def test_rapidocr_verification_follows_the_tests_and_requires_rbitnet(goal):
    catalog = load_catalog()
    plan = compile_goal(goal, catalog, rbitnet=True, rapidocr=True)
    assert plan["graph_id"] == "notes-rbitnet-ocr"
    assert plan["steps"][:-1] == compile_goal(goal, catalog, rbitnet=True)["steps"]
    step = plan["steps"][-1]
    assert (step["id"], step["action"], step["capability_id"], step["depends_on"]) == (
        "verify_desktop", "test", "notes.verify_desktop", ["verify"],
    )
    assert plan["expected_validation"]["desktop"] == {
        "protocol": "notes-desktop-ocr-v2", "ocr_after_restart": True, "sqlite_after_restart": True,
    }
    with pytest.raises(PlanningError) as denied:
        compile_goal(goal, catalog, rapidocr=True)
    assert denied.value.error.code == ErrorCode.CONTRACT_PRECONDITION_FAILED
