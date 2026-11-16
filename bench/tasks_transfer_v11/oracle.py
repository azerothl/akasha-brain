"""Contrôle indépendant des trois listes visibles et de la base SQLite."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from board import Board

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from tasks_oracle_deltas import FILTERS, encode_oracle


def snapshot(path: Path) -> tuple[list, str]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = [list(row) for row in connection.execute("SELECT * FROM support_tickets ORDER BY ticket_id")]
    return rows, sha256(path.read_bytes()).hexdigest()


def main(phase: str, selection: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tickets.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        connection.executemany("INSERT INTO support_tickets VALUES (?, ?, ?, ?, ?)", seed["tickets"])
    initial = snapshot(database)
    if initial[0] != seed["tickets"]:
        raise RuntimeError("État initial inattendu.")
    titles = {key: title for key, title, *_ in initial[0]}
    expected = {label: [f"{key} | {titles[key]}" for key in seed["visible_ids"][label]] for label in FILTERS}
    observed = {}
    unchanged = True
    board = Board(ROOT / "reference.py" if phase == "reference" else selection, database)
    try:
        board.update()
        for label in FILTERS:
            button = board.filters[label]
            button.invoke()
            board.update()
            if not button.instate(["selected"]) or not board.entries.winfo_viewable():
                raise RuntimeError("Le filtre n’est pas visible.")
            if any(board.entries.bbox(row) is None for row in range(board.entries.size())):
                raise RuntimeError("Une ligne n’est pas visible.")
            observed[label] = list(board.entries.get(0, "end"))
            unchanged &= snapshot(database) == initial
    finally:
        board.destroy()
    return encode_oracle(expected, observed, unchanged)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
