"""Sélection du tableau de répartition."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_cards(database: str, view: str) -> list[tuple[int, str]]:
    query = "SELECT card_id, title FROM work_cards"
    if view == "pending":
        query += " WHERE completed = 0"
    elif view == "closed":
        query += " WHERE completed = 1"
    elif view != "all":
        raise ValueError(f"Filtre inconnu : {view}")
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(query + " ORDER BY card_id").fetchall()


if __name__ == "__main__":
    print(json.dumps(select_cards(sys.argv[1], sys.argv[2])))
