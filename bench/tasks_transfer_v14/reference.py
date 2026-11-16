"""Témoin indépendant du filtre SQLite candidat."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_interventions(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT * FROM interventions ORDER BY ticket_id").fetchall()
    if view == "pending":
        return [(ticket, subject) for ticket, subject, queue, confirmation in rows
                if queue in {"normal", "deferred"} and confirmation is None]
    if view == "closed":
        return [(ticket, subject) for ticket, subject, _, confirmation in rows if confirmation is not None]
    if view == "all":
        return [(ticket, subject) for ticket, subject, _, _ in rows]
    raise ValueError(view)


if __name__ == "__main__":
    print(json.dumps(select_interventions(Path(sys.argv[1]), sys.argv[2])))
