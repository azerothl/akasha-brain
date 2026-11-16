"""Témoin Python indépendant des clauses utilisées par le candidat."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_tickets(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT * FROM support_tickets ORDER BY ticket_id").fetchall()
    if view == "pending":
        return [(key, title) for key, title, status, archived, _ in rows if status == "open" and archived is None]
    if view == "closed":
        return [(key, title) for key, title, status, archived, code in rows
                if archived is None and status == "done" and code is not None and code.strip(" ")]
    if view != "all":
        raise ValueError(view)
    return [(key, title) for key, title, *_ in rows]


if __name__ == "__main__":
    print(json.dumps(select_tickets(Path(sys.argv[1]), sys.argv[2])))
