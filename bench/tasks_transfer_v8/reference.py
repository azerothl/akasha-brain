"""Sélection témoin à partir des tâches et des reçus lus séparément."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_tasks(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        tasks = db.execute("SELECT task_id, title FROM task_log ORDER BY task_id").fetchall()
        closed_ids = {task_id for task_id, accepted in db.execute("SELECT task_id, accepted FROM close_receipt")
                      if accepted == 1}
    if view == "closed":
        return [row for row in tasks if row[0] in closed_ids]
    if view == "pending":
        return [row for row in tasks if row[0] not in closed_ids]
    return tasks


if __name__ == "__main__":
    print(json.dumps(select_tasks(Path(sys.argv[1]), sys.argv[2])))
