"""Lister les tâches dont l'état courant dépend du dernier événement."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_items(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT t.id, t.title FROM tasks AS t"
    if view == "pending":
        query += " WHERE NOT EXISTS (SELECT 1 FROM events AS e WHERE e.task_id = t.id AND e.status = 'closed')"
    elif view == "closed":
        query += (
            " WHERE (SELECT e.status FROM events AS e WHERE e.task_id = t.id"
            " ORDER BY e.number DESC LIMIT 1) = 'closed'"
        )
    elif view != "all":
        raise ValueError(view)
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY t.id").fetchall()


if __name__ == "__main__":
    print(json.dumps(visible_items(sys.argv[1], sys.argv[2]), ensure_ascii=False))
