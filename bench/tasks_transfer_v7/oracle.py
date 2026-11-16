"""Contrôle indépendant des trois filtres visibles et du fichier SQLite."""

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


def snapshot(path: Path) -> tuple[list, list, str]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        statuses = [list(row) for row in db.execute("SELECT * FROM state_catalog ORDER BY code")]
        items = [list(row) for row in db.execute("SELECT * FROM queue_items ORDER BY item_id")]
    return statuses, items, sha256(path.read_bytes()).hexdigest()


def main(phase: str, selection: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        db.execute("PRAGMA foreign_keys = ON")
        db.executemany("INSERT INTO state_catalog VALUES (?, ?, ?)", seed["statuses"])
        db.executemany("INSERT INTO queue_items VALUES (?, ?, ?)", seed["items"])
    initial = snapshot(database)
    if initial[:2] != (seed["statuses"], seed["items"]):
        raise RuntimeError("État initial inattendu.")

    titles = {item_id: title for item_id, title, _ in initial[1]}
    expected = {
        label: [f"{item_id} | {titles[item_id]}" for item_id in seed["expected_ids"][label]]
        for label in FILTERS
    }
    observed = {}
    unchanged = True
    board = Board(ROOT / "reference.py" if phase == "reference" else selection, database)
    try:
        for index, label in enumerate(FILTERS):
            board.selector.current(index)
            board.selector.event_generate("<<ComboboxSelected>>")
            board.update()
            if board.selector.get() != label or not board.entries.winfo_viewable():
                raise RuntimeError("Impossible d'attester le filtre visible.")
            if any(board.entries.bbox(row) is None for row in range(board.entries.size())):
                raise RuntimeError("Une ligne n'est pas visible dans la liste.")
            observed[label] = list(board.entries.get(0, "end"))
            unchanged &= snapshot(database) == initial
    finally:
        board.destroy()
    return encode_oracle(expected, observed, unchanged)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
