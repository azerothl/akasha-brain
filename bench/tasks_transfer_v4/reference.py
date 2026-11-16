"""Témoin indépendant du filtre fondé sur le dernier événement."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def rows_for(database: str, view: str) -> list:
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        tasks = db.execute("SELECT id, title FROM tasks ORDER BY id").fetchall()
        history = db.execute("SELECT task_id, status FROM events ORDER BY number").fetchall()
    current = dict(history)
    return [(item_id, title) for item_id, title in tasks
            if view == "all" or (current.get(item_id, "open") == "closed") == (view == "closed")]


if __name__ == "__main__":
    print(json.dumps(rows_for(*sys.argv[1:]), ensure_ascii=False))
