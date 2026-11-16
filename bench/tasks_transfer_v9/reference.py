"""Témoin qui classe les tâches après lecture des deux tables."""

from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

REFERENCE_DAY = "2026-11-15"


def select_tasks(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT * FROM work_items ORDER BY item_id").fetchall()
        dependencies = defaultdict(list)
        for item_id, required_id in db.execute("SELECT item_id, required_item_id FROM prerequisites"):
            dependencies[item_id].append(required_id)

    completed = {item_id for item_id, _, closed_on, _ in rows if closed_on is not None}
    if view == "closed":
        return [(item_id, title) for item_id, title, _, _ in rows if item_id in completed]
    if view == "all":
        return [(item_id, title) for item_id, title, _, _ in rows]
    return [
        (item_id, title) for item_id, title, _, deferred_until in rows
        if item_id not in completed
        and (deferred_until is None or deferred_until <= REFERENCE_DAY)
        and all(required_id in completed for required_id in dependencies[item_id])
    ]


if __name__ == "__main__":
    print(json.dumps(select_tasks(Path(sys.argv[1]), sys.argv[2])))
