"""Sélection des tâches sur le tableau des clôtures."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_tasks(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT t.task_id, t.title FROM task_log AS t"
    if view == "closed":
        query += " JOIN close_receipt AS r ON r.task_id = t.task_id WHERE r.accepted = 1"
    elif view == "pending":
        query += " WHERE NOT EXISTS (SELECT 1 FROM close_receipt AS r WHERE r.task_id = t.task_id AND r.accepted = 1)"
    elif view != "all":
        raise ValueError(f"Filtre inconnu : {view}")
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY t.task_id").fetchall()


if __name__ == "__main__":
    print(json.dumps(select_tasks(sys.argv[1], sys.argv[2])))
