"""Témoin Python des interventions sélectionnées."""

from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys


def select_interventions(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT * FROM interventions ORDER BY intervention_id").fetchall()
    if view == "pending":
        cutoff = date(2026, 3, 19)
        return [(key, title) for key, title, phase, released, suspended in rows
                if phase == "queued" and not suspended and (released is None or date.fromisoformat(released) <= cutoff)]
    if view == "closed":
        return [(key, title) for key, title, phase, *_ in rows if phase == "finished"]
    if view != "all":
        raise ValueError(view)
    return [(key, title) for key, title, *_ in rows]


if __name__ == "__main__":
    print(json.dumps(select_interventions(Path(sys.argv[1]), sys.argv[2])))
