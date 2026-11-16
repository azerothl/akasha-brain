"""Témoin indépendant du tri du tableau des échéances."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_tasks(database: str, view: str) -> list[tuple[int, str]]:
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute("SELECT id, title, finished, due FROM tasks ORDER BY id").fetchall()
    if view == "pending":
        rows = sorted((row for row in rows if row[2] == 0), key=lambda row: (row[3] is None, row[3], row[0]))
    elif view == "closed":
        rows = [row for row in rows if row[2] == 1]
    return [(task_id, title) for task_id, title, _, _ in rows]


if __name__ == "__main__":
    print(json.dumps(visible_tasks(*sys.argv[1:]), ensure_ascii=False))
