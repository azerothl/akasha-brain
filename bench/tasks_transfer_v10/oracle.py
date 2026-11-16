"""Vérifier l’ordre des lignes visibles et l’intégrité de SQLite."""

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
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        cards = [list(row) for row in db.execute("SELECT * FROM work_cards ORDER BY card_id")]
    return cards, sha256(path.read_bytes()).hexdigest()


def main(phase: str, selection: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        db.executemany("INSERT INTO work_cards VALUES (?, ?, ?, ?)", seed["cards"])
    initial = snapshot(database)
    if initial[0] != seed["cards"]:
        raise RuntimeError("État initial inattendu.")

    titles = {card_id: title for card_id, title, _, _ in initial[0]}
    expected = {
        label: [f"{card_id} | {titles[card_id]}" for card_id in seed["visible_ids"][label]]
        for label in FILTERS
    }
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
