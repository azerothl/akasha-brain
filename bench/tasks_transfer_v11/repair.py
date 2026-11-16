"""Lecture des tickets visibles dans le tableau."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

VIEWS = {"pending": "À faire", "closed": "Terminées", "all": "Toutes"}
FILTER_CLAUSES = {
    "À faire": "WHERE status = 'open' AND archived_at IS NULL ORDER BY ticket_id",
    "Terminées": "WHERE status = 'done' ORDER BY ticket_id",
    "Toutes": "ORDER BY ticket_id",
}


def select_tickets(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        statement = "SELECT ticket_id, title FROM support_tickets " + FILTER_CLAUSES[VIEWS[view]]
        return connection.execute(statement).fetchall()


if __name__ == "__main__":
    print(json.dumps(select_tickets(Path(sys.argv[1]), sys.argv[2])))
