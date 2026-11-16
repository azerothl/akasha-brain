"""Contrôler les listes visibles et l'intégrité SQLite."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from deadline_board import DeadlineBoard

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from tasks_oracle_deltas import FILTERS, encode_oracle


def snapshot(database: Path) -> tuple[list, str]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        rows = [list(row) for row in db.execute("SELECT id, title, finished, due FROM tasks ORDER BY id")]
    return rows, sha256(database.read_bytes()).hexdigest()


def main(phase: str, module: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, finished INTEGER NOT NULL, due TEXT)"
        )
        db.executemany("INSERT INTO tasks VALUES (?, ?, ?, ?)", seed)
    initial = snapshot(database)
    if initial[0] != seed:
        raise RuntimeError("État initial inattendu.")

    pending = [row for row in initial[0] if row[2] == 0]
    dated = sorted((row for row in pending if row[3] is not None), key=lambda row: (row[3], row[0]))
    expected_rows = {
        "À faire": dated + [row for row in pending if row[3] is None],
        "Terminées": [row for row in initial[0] if row[2] == 1],
        "Toutes": initial[0],
    }
    expected = {name: [f"{task_id} | {title}" for task_id, title, _, _ in rows]
                for name, rows in expected_rows.items()}

    board = DeadlineBoard(ROOT / "reference.py" if phase == "reference" else module, database)
    observed = {}
    unchanged = True
    try:
        board.update()
        for name in FILTERS:
            board.buttons[name].invoke()
            board.update()
            if board.selection.get() != name or not board.rows.winfo_viewable():
                raise RuntimeError("Le filtre ou la liste à contrôler n'est pas visible.")
            if any(board.rows.bbox(row) is None for row in range(board.rows.size())):
                raise RuntimeError("Une ligne se trouve hors de la liste visible.")
            observed[name] = list(board.rows.get(0, "end"))
            unchanged &= snapshot(database) == initial
    finally:
        board.destroy()
    return encode_oracle(expected, observed, unchanged)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
