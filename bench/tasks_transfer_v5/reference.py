"""Témoin indépendant pour le filtre de liste de contrôle."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_tasks(database: str, view: str) -> list[tuple[int, str]]:
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        tasks = db.execute("SELECT id, title FROM tasks ORDER BY id").fetchall()
        completed = {
            task_id for (task_id,) in db.execute(
                "SELECT task_id FROM steps WHERE required = 1 GROUP BY task_id"
                " HAVING COUNT(*) = SUM(CASE WHEN checked = 1 THEN 1 ELSE 0 END)"
            )
        }
    return [(task_id, title) for task_id, title in tasks if view == "all" or (task_id in completed) == (view == "closed")]


if __name__ == "__main__":
    print(json.dumps(visible_tasks(*sys.argv[1:]), ensure_ascii=False))
