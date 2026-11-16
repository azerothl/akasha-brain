"""Sélecteur du tableau de préparation."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

AS_OF = "2026-11-15"


def select_tasks(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT item_id, title FROM work_items"
    if view == "pending":
        query += " WHERE closed_on IS NULL"
    elif view == "closed":
        query += " WHERE closed_on IS NOT NULL"
    elif view != "all":
        raise ValueError(f"Filtre inconnu : {view}")
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY item_id").fetchall()


if __name__ == "__main__":
    print(json.dumps(select_tasks(sys.argv[1], sys.argv[2])))
