from contextlib import closing
import json
import sqlite3

import pytest

from akasha_brain.tasks_sql_specialist import decode_plan

COLUMNS = frozenset({"id", "owner", "score", "deadline"})


def query(plan):
    _, clause = decode_plan(json.dumps(plan), COLUMNS)
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE work (id INTEGER, owner TEXT, score INTEGER, deadline INTEGER)")
        db.executemany("INSERT INTO work VALUES (?, ?, ?, ?)", [
            (1, "O'Brien", 3, None), (2, None, 3, 9), (3, None, 1, 5), (4, "Mia", 5, 2),
        ])
        return [row[0] for row in db.execute("SELECT id FROM work " + clause)]


def test_structured_selection_parenthesizes_rules_and_places_nulls_explicitly():
    plan = {
        "where": ["or", ["=", "owner", "O'Brien"], ["and", ["isnull", "owner"], [">=", "score", 2]]],
        "order": [["score", "desc"], ["deadline", "asc", "last"], ["id", "asc"]],
    }
    assert query(plan) == [2, 1]


def test_ordered_groups_keep_unmatched_rows_in_the_last_group():
    plan = {
        "where": None,
        "order": [[["case", ["isnull", "owner"], [">=", "score", 4]], "asc"],
                  ["deadline", "desc", "first"], ["id", "asc"]],
    }
    assert query(plan) == [2, 3, 4, 1]


@pytest.mark.parametrize("answer", [
    '{"where":null,"where":null,"order":[["id","asc"]]}',
    '{"where":["=","owner",null],"order":[["id","asc"]]}',
    '{"where":["=","score",true],"order":[["id","asc"]]}',
    '{"where":null,"order":[["id; DROP TABLE work","asc"]]}',
    '{"where":null,"order":[["deadline","asc","COALESCE"]]}',
    '{"where":null,"order":[["id","asc"]]} {"where":null,"order":[["id","desc"]]}',
])
def test_specialist_rejects_invalid_or_ambiguous_plans(answer):
    with pytest.raises(ValueError):
        decode_plan(answer, COLUMNS)
