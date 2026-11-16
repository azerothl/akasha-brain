"""Contrôler les widgets visibles et la base en lecture seule."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from board import Board

ROOT = Path(__file__).resolve().parent
LABELS = ("À faire", "Terminées", "Toutes")


def snapshot(path: Path) -> tuple[list, str]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        rows = [list(row) for row in db.execute("SELECT item_id, title, closed_at FROM backlog ORDER BY item_id")]
    return rows, sha256(path.read_bytes()).hexdigest()


def main(phase: str, selection: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE backlog (item_id INTEGER PRIMARY KEY, title TEXT NOT NULL, closed_at TEXT)")
        db.executemany("INSERT INTO backlog VALUES (?, ?, ?)", seed)
    initial = snapshot(database)
    if initial[0] != seed:
        raise RuntimeError("État initial inattendu.")
    board = Board(ROOT / "reference.py" if phase == "reference" else selection, database)
    mask = 0x59000000
    unchanged = snapshot(database) == initial
    try:
        for index, label in enumerate(LABELS):
            board.selector.current(index)
            board.selector.event_generate("<<ComboboxSelected>>")
            board.update()
            if board.selector.get() != label or not board.entries.winfo_viewable():
                raise RuntimeError("Impossible d'attester le filtre visible.")
            if any(board.entries.bbox(row) is None for row in range(board.entries.size())):
                raise RuntimeError("Une ligne n'est pas visible dans la liste.")
            expected = [
                f"{item_id} | {title}" for item_id, title, closed_at in initial[0]
                if index == 2 or (index == 0 and closed_at is None) or (index == 1 and closed_at is not None)
            ]
            if list(board.entries.get(0, "end")) == expected:
                mask |= 1 << index
            unchanged &= snapshot(database) == initial
    finally:
        board.destroy()
    return mask | (8 if unchanged else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
