"""Retourner les tâches du filtre sélectionné."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_tasks(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT t.id, t.title FROM tasks AS t"
    if view == "pending":
        query += (
            " WHERE NOT EXISTS (SELECT 1 FROM steps"
            " WHERE task_id = t.id AND required = 1 AND checked = 1)"
        )
    elif view == "closed":
        query += (
            " WHERE EXISTS (SELECT 1 FROM steps WHERE task_id = t.id AND required = 1)"
            " AND NOT EXISTS (SELECT 1 FROM steps WHERE task_id = t.id AND required = 1 AND checked IS NOT 1)"
        )
    elif view != "all":
        raise ValueError(view)
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY t.id").fetchall()


if __name__ == "__main__":
    print(json.dumps(visible_tasks(*sys.argv[1:]), ensure_ascii=False))
