from hashlib import sha256
import json
from pathlib import Path

import pytest

from akasha_brain.planning import PlanningError, compile_goal, load_catalog
from akasha_brain.tasks_transfer import (
    baseline_filter_regressions, distinct_proposal, evaluate_proposals, repair_prompt, replace_definition,
)
from bench.harness.tasks_oracle_deltas import FILTERS, decode_oracle, encode_oracle


def oracle_checks(passes, sqlite_unchanged=True):
    expected = {name: ["first"] for name in FILTERS}
    actual = {name: ["first"] if passed else [] for name, passed in zip(FILTERS, passes)}
    return decode_oracle(encode_oracle(expected, actual, sqlite_unchanged))


def test_tasks_compile_through_the_same_three_stage_repair_plan():
    root = Path(__file__).resolve().parents[1]
    goal = json.loads((root / "contracts/examples/goal_tasks_repair.json").read_text(encoding="utf-8"))
    catalog = load_catalog()
    plan = compile_goal(goal, catalog, rbitnet=True)
    assert plan["graph_id"] == "tasks-rbitnet"
    assert plan["graph_version"] == "1.6.0"
    assert plan["repair_context"] == {"sqlite_schema": "schema.sql", "target_filters": "latest_verdict_failures"}
    assert plan["repair_retry"] == {
        "max_attempts": 2, "on": "verification_failed", "after": "verify", "resume_at": "generate_diff",
        "feedback": "filter_deltas", "require_distinct_proposal": True,
        "protected_filters": "initial_passes",
    }
    assert [(stage["id"], stage["depends_on"]) for stage in plan["steps"]] == [
        ("localize", []), ("generate_diff", ["localize"]), ("verify", ["generate_diff"]),
    ]
    with pytest.raises(PlanningError):
        compile_goal(goal, catalog)
    with pytest.raises(PlanningError):
        compile_goal(goal, catalog, rbitnet=True, rapidocr=True)


def test_python_patch_changes_only_the_named_function_or_method():
    source = (
        "class Meter:\n"
        "    def read(self, raw: int) -> int:\n"
        "        return raw - 1\n"
        "\n"
        "def scale(x):\n"
        "    return x * 2\n"
    )
    response = "def read(self, raw: int) -> int:\n    return raw + 1"
    proposal = replace_definition(source, response)
    assert "-        return raw - 1" in proposal.diff and "+        return raw + 1" in proposal.diff
    expected = source.replace("return raw - 1", "return raw + 1")
    assert proposal.file_sha256 == sha256(expected.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="signature"):
        replace_definition(source, "def read(self, raw: int):\n    return raw")
    with pytest.raises(ValueError, match="seule définition"):
        replace_definition(source, response + "\n\ndef scale(x):\n    return 0")


def test_filter_and_sqlite_verdicts_are_independent():
    expected = {name: ["a", "b"] for name in FILTERS}
    actual = dict(zip(FILTERS, [["a", "c", "c"], ["b", "a"], ["a", "b"]]))
    result = decode_oracle(encode_oracle(expected, actual, False))
    assert list(result["filters"].values()) == [False, False, True] and result["sqlite_unchanged"] is False
    assert result["filter_deltas"]["À faire"] == {"missing": 1, "unexpected": 2, "wrong_order": False}
    assert result["filter_deltas"]["Terminées"] == {"missing": 0, "unexpected": 0, "wrong_order": True}
    saturated = decode_oracle(encode_oracle(expected, {name: ["z"] * 20 for name in FILTERS}, True))
    assert all(delta["unexpected"] == 15 for delta in saturated["filter_deltas"].values())


def test_repeat_rejects_the_same_diff_and_cosmetic_changes():
    source = "def scale(x):\n    return x * 2\n"
    first = replace_definition(source, "def scale(x):\n    return x + 3")
    cosmetic = replace_definition(source, "def scale(x):\n    return x+3  # updated")
    different = replace_definition(source, "def scale(x):\n    return x + 4")
    assert not distinct_proposal(first, first)
    assert first.diff != cosmetic.diff and not distinct_proposal(first, cosmetic)
    assert distinct_proposal(different, first)


@pytest.mark.parametrize("checks,accepted", [
    ([oracle_checks([True, True, True])], 1),
    ([oracle_checks([False, False, True]), oracle_checks([True, True, True])], 2),
    ([oracle_checks([False, False, True]), oracle_checks([True, False, True])], None),
    ([oracle_checks([True, True, True], False)] * 2, None),
])
def test_retry_gate_uses_the_first_complete_verdict_and_is_bounded(checks, accepted):
    attempts = []

    def run(attempt, previous):
        attempts.append((attempt, previous))
        return f"proposal {attempt}", checks[attempt - 1]

    assert evaluate_proposals(run, oracle_checks([False, True, True])) == accepted
    assert attempts[0] == (1, None)
    assert len(attempts) == len(checks)
    if len(checks) == 2:
        assert attempts[1] == (2, ("proposal 1", checks[0]))


def test_second_prompt_reports_the_candidate_checks_without_the_previous_diff():
    initial = oracle_checks([False, True, True])
    candidate = oracle_checks([True, True, False])
    schema = "CREATE TABLE meters (id INTEGER PRIMARY KEY, reading INTEGER NOT NULL);"
    source = "def example(): pass"
    first = replace_definition(source + "\n", "def example(): return 1")
    prompt = repair_prompt("Restore the requested behavior", source, initial,
                           sqlite_schema=schema, previous_checks=candidate)
    assert first.diff not in prompt and "return 1" not in prompt
    assert "Toutes: FAIL. Missing rows: 1. Unexpected rows: 0. Order mismatch: not measured." in prompt
    assert "SQLite state preserved: PASS" in prompt
    assert "these filters passed on the original module and must still pass: Terminées, Toutes." in prompt
    assert "Restore the original behavior of these filters broken by the previous proposal: Toutes." in prompt
    assert baseline_filter_regressions(initial, candidate) == ["Toutes"]
    first_prompt = repair_prompt("Restore the requested behavior", source, initial, sqlite_schema=schema)
    expected_context = f"SQLite schema (DDL):\n```sql\n{schema}\n```\n\nPython module:\n{source}"
    assert first_prompt.endswith(expected_context)
    assert prompt.endswith(expected_context)
    assert "Independent verification after the first attempt:" in prompt
    assert "Independent verification after the first attempt:" not in first_prompt
    assert "Required target filters: À faire." in first_prompt
    assert "Required target filters: Toutes." in prompt
    assert "Required target filters: À faire." not in prompt
    for request in (first_prompt, prompt):
        assert "Change the executable logic that selects or orders the rows for each target filter." in request


def test_sqlite_only_failure_does_not_require_a_filter_change():
    initial = oracle_checks([False, True, True])
    candidate = oracle_checks([True, True, True], sqlite_unchanged=False)
    prompt = repair_prompt("Restore the requested behavior", "def example(): pass\n", initial,
                           sqlite_schema="CREATE TABLE meters (id INTEGER PRIMARY KEY);", previous_checks=candidate)
    assert "SQLite state preserved: FAIL" in prompt
    assert "Required target filters:" not in prompt
