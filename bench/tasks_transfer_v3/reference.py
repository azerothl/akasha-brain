"""Témoin indépendant pour le tableau réservé."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


if __name__ == "__main__":
    database, view = sys.argv[1:]
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT item_id, title, closed_at FROM backlog ORDER BY item_id").fetchall()
    shown = [
        [item_id, title] for item_id, title, closed_at in rows
        if view == "all" or (view == "closed" and closed_at is not None) or (view == "pending" and closed_at is None)
    ]
    print(json.dumps(shown, ensure_ascii=False))
