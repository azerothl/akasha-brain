"""Sélection des interventions visibles du tableau d’atelier."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

VIEWS = {"pending": "À faire", "closed": "Terminées", "all": "Toutes"}
FILTER_CLAUSES = {
    "À faire": "WHERE queue <> 'cancelled' ORDER BY ticket_id",
    "Terminées": "WHERE confirmed_at IS NOT NULL ORDER BY ticket_id",
    "Toutes": "ORDER BY ticket_id",
}


def select_interventions(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        query = "SELECT ticket_id, subject FROM interventions " + FILTER_CLAUSES[VIEWS[view]]
        return connection.execute(query).fetchall()


if __name__ == "__main__":
    print(json.dumps(select_interventions(Path(sys.argv[1]), sys.argv[2])))
