"""Sélection témoin qui classe les tâches après lecture des deux tables."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        terminal = dict(db.execute("SELECT code, is_terminal FROM state_catalog"))
        items = db.execute("SELECT item_id, title, state_code FROM queue_items ORDER BY item_id").fetchall()
    return [
        (item_id, title) for item_id, title, status in items
        if view == "all" or (view == "closed") == bool(terminal[status])
    ]


if __name__ == "__main__":
    print(json.dumps(select(Path(sys.argv[1]), sys.argv[2])))
