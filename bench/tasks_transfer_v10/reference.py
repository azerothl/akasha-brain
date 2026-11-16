"""Témoin qui groupe les cartes par responsable après lecture de SQLite."""

from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def select_cards(database: Path, view: str) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT * FROM work_cards ORDER BY card_id").fetchall()
    if view in ("pending", "closed"):
        return [(card_id, title) for card_id, title, done, _ in rows if done == (view == "closed")]

    groups = defaultdict(list)
    for card_id, title, _, assignee in rows:
        groups[(assignee or "").strip().casefold()].append((card_id, title))
    unassigned = groups.pop("", [])
    return [card for name in sorted(groups) for card in groups[name]] + unassigned


if __name__ == "__main__":
    print(json.dumps(select_cards(Path(sys.argv[1]), sys.argv[2])))
