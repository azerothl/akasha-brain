import pytest

from akasha_brain.tasks_sql_transfer import render_patch, response_clause


def test_only_the_selected_filter_literal_is_rewritten():
    source = 'FILTER_CLAUSES = {"À faire": "WHERE x = 0", "Toutes": "ORDER BY id"}\nOUTSIDE = 123\n'
    clause = response_clause("```sql\nWHERE x = 1 ORDER BY id\n```")
    diff, checksum = render_patch(source, {"À faire": clause})
    assert '-FILTER_CLAUSES = {"À faire": "WHERE x = 0", "Toutes": "ORDER BY id"}' in diff
    assert '+FILTER_CLAUSES = {"À faire": \'WHERE x = 1 ORDER BY id\', "Toutes": "ORDER BY id"}' in diff
    assert "\n OUTSIDE = 123\n" in diff
    assert len(checksum) == 64


def test_response_uses_the_first_complete_leading_sql_block():
    response = "```sql\nORDER BY priority DESC, id\n```\n\n```sql\nORDER BY id\n```"
    assert response_clause(response) == "ORDER BY priority DESC, id"


@pytest.mark.parametrize("response", [
    "WHERE id = ?",
    "WHERE TRUE; SELECT 1",
    "WHERE TRUE UNION SELECT 1",
    "WHERE load_extension('test')",
])
def test_sql_response_rejects_changes_to_the_query_structure(response):
    with pytest.raises(ValueError):
        response_clause(response)
