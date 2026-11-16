"""Observer les widgets et vérifier séparément les lignes SQLite."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sqlite3

ROOT = Path(__file__).resolve().parent
LABELS = ("À faire", "Terminées", "Toutes")
FAULT = "FILTER_VALUES = (None, 1, None)"
REFERENCE = "FILTER_VALUES = (0, 1, None)"


def initialize(work: Path, reference: bool) -> None:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE work_items (id INTEGER PRIMARY KEY, title TEXT NOT NULL, closed INTEGER NOT NULL)")
        db.executemany("INSERT INTO work_items VALUES (?, ?, ?)", seed)
    (work / "initial.sha256").write_text(sha256(database.read_bytes()).hexdigest(), encoding="ascii")
    source = (ROOT / "board.py").read_text(encoding="utf-8")
    if reference:
        if source.count(FAULT) != 1:
            raise RuntimeError("Le témoin corrigé s'applique à une version figée du tableau.")
        source = source.replace(FAULT, REFERENCE, 1)
    (work / "board.py").write_text(source, encoding="utf-8")


def observe(work: Path) -> None:
    board_type = runpy.run_path(str(work / "board.py"))["TasksBoard"]
    board = board_type(work / "tasks.db")
    seen = {}
    try:
        for index, label in enumerate(LABELS):
            board.selector.current(index)
            board.selector.event_generate("<<ComboboxSelected>>")
            board.update()
            rows = board.entries
            if board.selector.get() != label or not rows.winfo_viewable():
                raise RuntimeError("Le filtre ou la liste du tableau est inaccessible.")
            if any(rows.bbox(index) is None for index in range(rows.size())):
                raise RuntimeError("Une ligne se trouve hors de la liste visible.")
            seen[label] = list(rows.get(0, "end"))
    finally:
        board.destroy()
    (work / "observation.json").write_text(json.dumps(seen), encoding="utf-8")


def verify(work: Path) -> int:
    database = work / "tasks.db"
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        actual = [list(row) for row in db.execute("SELECT id, title, closed FROM work_items ORDER BY id")]
    state_unchanged = actual == seed and sha256(database.read_bytes()).hexdigest() == (
        work / "initial.sha256"
    ).read_text(encoding="ascii")
    seen = json.loads((work / "observation.json").read_text(encoding="utf-8"))
    titles = [title for _, title, _ in seed]
    result = 0x59000000 | (int(state_unchanged) << 9)
    for index, label in enumerate(LABELS):
        rows = seen[label]
        mask = sum(1 << offset for offset, title in enumerate(titles) if title in rows)
        if rows != [title for title in titles if title in rows]:
            mask |= 4
        result |= mask << (3 * index)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("initialize", "observe", "verify"))
    parser.add_argument("work", type=Path)
    parser.add_argument("--reference", action="store_true")
    args = parser.parse_args()
    if args.phase == "initialize":
        initialize(args.work, args.reference)
    elif args.phase == "observe":
        observe(args.work)
    else:
        return verify(args.work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
