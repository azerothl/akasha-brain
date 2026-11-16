"""Témoin Python de l’ordre visible, indépendant de la requête candidate."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_orders(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT * FROM work_orders ORDER BY order_id").fetchall()
    if view in ("pending", "closed"):
        phase = "open" if view == "pending" else "done"
        return [(key, title) for key, title, state, _ in rows if state == phase]
    if view != "all":
        raise ValueError(view)
    scores = sorted({score for _, _, _, score in rows if score is not None}, reverse=True)
    scores.append(None)
    return [(key, title) for score in scores for key, title, _, actual in rows if score == actual]


if __name__ == "__main__":
    print(json.dumps(select_orders(Path(sys.argv[1]), sys.argv[2])))
