"""Vérifier l'affichage et l'état SQLite de la variante de liste de contrôle."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from checklist import Checklist

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from tasks_oracle_deltas import FILTERS, encode_oracle


def snapshot(database: Path) -> tuple[dict, str]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        state = {
            "tasks": [list(row) for row in db.execute("SELECT id, title FROM tasks ORDER BY id")],
            "steps": [list(row) for row in db.execute("SELECT id, task_id, required, checked FROM steps ORDER BY id")],
        }
    return state, sha256(database.read_bytes()).hexdigest()


def main(phase: str, module: Path, work: Path) -> int:
    seed = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    database = work / "tasks.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        db.execute("CREATE TABLE steps (id INTEGER PRIMARY KEY, task_id INTEGER, required INTEGER, checked INTEGER)")
        db.executemany("INSERT INTO tasks VALUES (?, ?)", seed["tasks"])
        db.executemany("INSERT INTO steps VALUES (?, ?, ?, ?)", seed["steps"])
    initial = snapshot(database)
    if initial[0] != seed:
        raise RuntimeError("État initial inattendu.")

    mandatory = {}
    for _, task_id, required, checked in initial[0]["steps"]:
        if required:
            mandatory.setdefault(task_id, []).append(checked)
    closed = {task for task, steps in mandatory.items() if all(checked == 1 for checked in steps)}
    expected = {name: [] for name in FILTERS}
    for task, title in initial[0]["tasks"]:
        row = f"{task} | {title}"
        expected["Toutes"].append(row)
        expected["Terminées" if task in closed else "À faire"].append(row)

    board = Checklist(ROOT / "reference.py" if phase == "reference" else module, database)
    observed = {}
    unchanged = True
    try:
        board.update()
        for index, name in enumerate(FILTERS):
            board.tabs.select(index)
            board.refresh()
            board.update()
            rows = board.lists[name]
            if board.tabs.tab(board.tabs.select(), "text") != name or not rows.winfo_viewable():
                raise RuntimeError("Onglet de vérification inaccessible.")
            if any(rows.bbox(row) is None for row in range(rows.size())):
                raise RuntimeError("Une ligne se trouve hors de la liste visible.")
            observed[name] = list(rows.get(0, "end"))
            unchanged &= snapshot(database) == initial
    finally:
        board.destroy()
    return encode_oracle(expected, observed, unchanged)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
