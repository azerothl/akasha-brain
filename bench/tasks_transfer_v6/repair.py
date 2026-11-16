"""Lire les tâches pour un filtre du tableau des échéances."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_tasks(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT id, title FROM tasks"
    if view == "pending":
        query += " WHERE finished = 0"
    elif view == "closed":
        query += " WHERE finished = 1"
    elif view != "all":
        raise ValueError(view)
    query += " ORDER BY id"
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query).fetchall()


if __name__ == "__main__":
    print(json.dumps(visible_tasks(*sys.argv[1:]), ensure_ascii=False))
