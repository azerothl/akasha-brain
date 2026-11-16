"""Clauses de sélection du tableau synthétique de développement."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

FILTER_CLAUSES = {
    "À faire": "WHERE state = 'open' ORDER BY id",
    "Terminées": "WHERE state = 'closed' ORDER BY id",
    "Toutes": "ORDER BY id",
}


def select_jobs(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        return connection.execute("SELECT id, title FROM jobs " + FILTER_CLAUSES[view]).fetchall()


if __name__ == "__main__":
    print(json.dumps(select_jobs(Path(sys.argv[1]), sys.argv[2])))
