"""Module de sélection du tableau de suivi."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def visible_items(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT item_id, title FROM queue_items"
    if view == "pending":
        query += " WHERE state_code = 'new'"
    elif view == "closed":
        query += " WHERE state_code IN (SELECT code FROM state_catalog WHERE is_terminal = 1)"
    elif view != "all":
        raise ValueError(f"Filtre inconnu : {view}")
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY item_id").fetchall()


if __name__ == "__main__":
    print(json.dumps(visible_items(sys.argv[1], sys.argv[2])))
