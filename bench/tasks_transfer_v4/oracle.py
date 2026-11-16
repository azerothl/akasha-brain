"""Contrôler les trois filtres visibles et l'intégrité de toute la base."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from dashboard import Dashboard

ROOT = Path(__file__).resolve().parent
LABELS = ("À faire", "Terminées", "Toutes")
VIEWS = ("pending", "closed", "all")


def snapshot(path: Path) -> tuple[dict, str]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        rows = {
            "tasks": [list(row) for row in db.execute("SELECT id, title FROM tasks ORDER BY id")],
            "events": [list(row) for row in db.execute("SELECT number, task_id, status FROM events ORDER BY number")],
        }
    return rows, sha256(path.read_bytes()).hexdigest()


def main(phase: str, module: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        db.execute("CREATE TABLE events (number INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, status TEXT NOT NULL)")
        db.executemany("INSERT INTO tasks VALUES (?, ?)", seed["tasks"])
        db.executemany("INSERT INTO events VALUES (?, ?, ?)", seed["events"])
    initial = snapshot(database)
    if initial[0] != seed:
        raise RuntimeError("État initial inattendu.")
    last_status = {item_id: status for _, item_id, status in initial[0]["events"]}
    expected = {
        label: [
            f"{item_id} | {title}" for item_id, title in initial[0]["tasks"]
            if view == "all" or (view == "closed" and last_status.get(item_id) == "closed")
            or (view == "pending" and last_status.get(item_id) != "closed")
        ]
        for label, view in zip(LABELS, VIEWS)
    }
    board = Dashboard(ROOT / "reference.py" if phase == "reference" else module, database)
    verdict = 0x59000000
    unchanged = snapshot(database) == initial
    try:
        for index, (label, view) in enumerate(zip(LABELS, VIEWS)):
            board.buttons[label].invoke()
            board.update()
            if board.selection.get() != view or not board.entries.winfo_viewable():
                raise RuntimeError("Le filtre ou la liste à contrôler n'est pas visible.")
            if any(board.entries.bbox(row) is None for row in range(board.entries.size())):
                raise RuntimeError("Une ligne attendue de l'observation est hors de la liste visible.")
            if list(board.entries.get(0, "end")) == expected[label]:
                verdict |= 1 << index
            unchanged &= snapshot(database) == initial
    finally:
        board.destroy()
    return verdict | (8 if unchanged else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
