import json

import pytest

from akasha_brain import tasks_sql_specialist_v2 as coverage
from akasha_brain import tasks_sql_specialist_v3 as specialist


REQUIRED = {
    "where": ["and", ["=", "state", "open"], ["or", ["isnull", "hold"], ["<=", "hold", 7]]],
    "order": [[["case", ["isnull", "due"], ["<=", "due", 3]], "asc"], ["due", "asc", "last"], ["id", "asc"]],
}
FLAT = {"where": "A & (B | C)", "groups": "D; E", "order": "due asc last; id asc"}
COLUMNS = frozenset({"state", "hold", "due", "id"})


def test_flat_plan_round_trips_through_coverage_and_sql_compilation():
    payload, repaired = specialist.parse_response(json.dumps(FLAT))
    assert not repaired
    assert specialist.expand_plan(payload, REQUIRED) == REQUIRED
    clause = coverage.compile_checked(specialist.expand_plan(payload, REQUIRED), REQUIRED, COLUMNS)
    assert 'ORDER BY CASE WHEN ("due" IS NULL) THEN 0' in clause
    assert clause.endswith('"due" ASC NULLS LAST, "id" ASC')


def test_one_trailing_brace_preserves_the_payload():
    assert specialist.parse_response(json.dumps(FLAT) + "}") == (FLAT, True)


@pytest.mark.parametrize("answer", [
    json.dumps(FLAT) + "}}",
    json.dumps(FLAT) + " {}",
    '{"where":"A","where":"B","groups":"","order":"id asc"}',
    '{"where":["A"],"groups":"","order":"id asc"}',
])
def test_response_rejects_ambiguous_json(answer):
    with pytest.raises(ValueError):
        specialist.parse_response(answer)


@pytest.mark.parametrize("where", ["A & Z", "A; DROP TABLE jobs"])
def test_only_declared_atom_names_and_supported_operators_are_accepted(where):
    with pytest.raises(ValueError):
        specialist.expand_plan({**FLAT, "where": where}, REQUIRED)


@pytest.mark.parametrize(("override", "issue"), [
    ({"where": "A & B | C"}, "Selection"),
    ({"groups": "E; D"}, "Group coverage"),
    ({"order": "due asc; id asc"}, "NULL placement"),
])
def test_expanded_plan_cannot_bypass_coverage(monkeypatch, override, issue):
    def compilation_forbidden(*args):
        pytest.fail("Compilation invoked despite a coverage error.")

    monkeypatch.setattr(coverage, "compile_plan", compilation_forbidden)
    plan = specialist.expand_plan({**FLAT, **override}, REQUIRED)
    with pytest.raises(coverage.CoverageError, match=issue):
        coverage.compile_checked(plan, REQUIRED, COLUMNS)
