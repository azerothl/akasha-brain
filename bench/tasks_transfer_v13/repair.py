"""Sélection des ordres visibles."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

VIEWS = {"pending": "À faire", "closed": "Terminées", "all": "Toutes"}
FILTER_CLAUSES = {
    "À faire": "WHERE phase = 'open' ORDER BY order_id",
    "Terminées": "WHERE phase = 'done' ORDER BY order_id",
    "Toutes": "ORDER BY order_id",
}


def select_orders(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        query = "SELECT order_id, title FROM work_orders " + FILTER_CLAUSES[VIEWS[view]]
        return connection.execute(query).fetchall()


if __name__ == "__main__":
    print(json.dumps(select_orders(Path(sys.argv[1]), sys.argv[2])))
