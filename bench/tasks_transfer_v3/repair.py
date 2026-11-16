"""Requêtes du tableau de suivi. Une tâche ouverte a closed_at à NULL."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_items(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT item_id, title FROM backlog"
    if view == "pending":
        query += " WHERE COALESCE(closed_at, '') IS NOT NULL"
    elif view == "closed":
        query += " WHERE closed_at IS NOT NULL"
    elif view != "all":
        raise ValueError(view)
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY item_id").fetchall()


if __name__ == "__main__":
    print(json.dumps(visible_items(sys.argv[1], sys.argv[2]), ensure_ascii=False))
