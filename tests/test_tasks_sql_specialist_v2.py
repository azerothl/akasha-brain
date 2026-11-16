from copy import deepcopy
import json

import pytest

from akasha_brain import tasks_sql_specialist_v2 as specialist


REQUIRED = {
    "where": ["and", ["=", "state", "ready"], ["or", ["isnull", "room"], ["=", "room", "main"]], [">=", "rank", 0]],
    "order": [[["case", ["isnull", "room"], ["=", "room", "main"]], "asc"],
              ["rank", "desc"], ["due", "asc", "last"]],
}
COLUMNS = frozenset({"state", "room", "rank", "due"})


def test_grouping_and_null_order_survive_compilation_of_an_equivalent_plan():
    plan = deepcopy(REQUIRED)
    plan["where"] = ["and", REQUIRED["where"][3], ["and", REQUIRED["where"][2], REQUIRED["where"][1]]]
    compiled = specialist.compile_checked(plan, REQUIRED, COLUMNS)
    assert '("state" = ' in compiled
    assert 'ORDER BY CASE WHEN ("room" IS NULL) THEN 0 WHEN ("room" = ' in compiled
    assert compiled.endswith('"rank" DESC, "due" ASC NULLS LAST')


@pytest.mark.parametrize(("edit", "issue"), [
    ("drop_condition", "Selection"),
    ("weaken_boolean_scope", "Selection"),
    ("add_condition", "Selection"),
    ("swap_groups", "Group"),
    ("change_key_direction", "Sort keys"),
    ("drop_null_placement", "NULL placement"),
    ("flip_null_placement", "NULL placement"),
])
def test_missing_or_incorrect_coverage_stops_before_sql_compilation(monkeypatch, edit, issue):
    plan = deepcopy(REQUIRED)
    if edit == "drop_condition":
        plan["where"].pop()
    elif edit == "weaken_boolean_scope":
        plan["where"][0] = "or"
    elif edit == "add_condition":
        plan["where"].append(["notnull", "due"])
    elif edit == "swap_groups":
        plan["order"][0][0][1:] = reversed(plan["order"][0][0][1:])
    elif edit == "change_key_direction":
        plan["order"][1][1] = "asc"
    elif edit == "drop_null_placement":
        plan["order"][-1].pop()
    else:
        plan["order"][-1][-1] = "first"

    def compilation_forbidden(*args):
        pytest.fail("Compilation invoked before coverage was satisfied.")

    monkeypatch.setattr(specialist, "compile_plan", compilation_forbidden)
    with pytest.raises(specialist.CoverageError, match=issue):
        specialist.compile_checked(specialist.parse_plan(json.dumps(plan)), REQUIRED, COLUMNS)


def test_group_predicates_cannot_replace_row_selection():
    required = {**REQUIRED, "where": None}
    with pytest.raises(specialist.CoverageError, match="keep every row"):
        specialist.verify_coverage(REQUIRED, required)
