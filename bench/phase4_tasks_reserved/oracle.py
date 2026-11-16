"""Contrôle les trois listes affichées et la base SQLite des deux cas réservés."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from tasks_oracle_deltas import FILTERS, encode_oracle


def snapshot(database: Path) -> tuple[list[tuple], str]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("L'intégrité SQLite est rompue.")
        rows = db.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    return rows, sha256(database.read_bytes()).hexdigest()


def handover_key(row: tuple) -> tuple:
    group = 2
    if row[2] == "closed" and row[3] >= 3:
        group = 0
    elif row[2] == "open" and (row[4] is None or row[3] == 4):
        group = 1
    return group, row[6] is None, -(row[6] or 0), row[5] is not None, row[5] or 0, -row[0]


def reference(rows: list[tuple], view: str, profile: str) -> list:
    if view == "À faire":
        selected = [row for row in rows if row[2] == "open"]
    elif view == "Terminées":
        selected = [row for row in rows if row[2] == "closed"]
        if profile == "closure":
            selected = [row for row in selected if row[4] is not None
                        and (row[3] == 5 or row[6] is not None and row[6] <= 9)]
            selected.sort(key=lambda row: (row[5] is not None, -(row[5] or 0), row[3], row[0]))
    else:
        selected = sorted(rows, key=handover_key) if profile == "handover" else rows
    return [(row[0], row[1]) for row in selected]


def run_module(module: Path, database: Path, view: str, work: Path) -> list:
    process = subprocess.run([sys.executable, "-B", str(module), str(database), view],
                             cwd=work, capture_output=True, encoding="utf-8", timeout=8,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode == 0:
        return json.loads(process.stdout)
    error = process.stderr.strip().splitlines()
    sql_errors = ("syntax error", "no such column", "no such function", "no such table",
                  "wrong number of arguments", "misuse of", "unrecognized token", "ambiguous column name")
    if (process.returncode == 1 and error and error[-1].startswith("sqlite3.OperationalError:")
            and any(message in error[-1] for message in sql_errors)):
        # La liste vide échoue au contrôle du filtre. Les deux autres filtres restent mesurés.
        return []
    process.check_returncode()
    raise RuntimeError("Sélection interrompue.")


def main(phase: str, module: Path, work: Path) -> int:
    fixture = json.loads((ROOT / "state.json").read_bytes())
    database = work / "reserved.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))
        db.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)", fixture["rows"])
    initial = snapshot(database)
    rows = initial[0]
    if rows != [tuple(row) for row in fixture["rows"]]:
        raise RuntimeError("État SQLite initial inattendu.")
    titles = {row[0]: row[1] for row in rows}
    expected = {view: [f"{key} | {titles[key]}" for key in fixture["visible_ids"][view]] for view in FILTERS}

    window = tk.Tk()
    window.title("Contrôle des listes Tâches")
    toolbar = ttk.Frame(window)
    toolbar.pack(padx=12, pady=12)
    active = tk.StringVar(window)
    entries = tk.Listbox(window, height=12, width=54)
    entries.pack(padx=12, pady=(0, 12))

    def display(view: str) -> None:
        selected = (reference(rows, view, fixture["id"]) if phase == "reference"
                    else run_module(module, database, view, work))
        entries.delete(0, tk.END)
        entries.insert(tk.END, *(f"{key} | {title}" for key, title in selected))

    def raise_callback(_type, value, traceback):
        raise value.with_traceback(traceback)

    window.report_callback_exception = raise_callback
    observed = {}
    intact = True
    try:
        for view in FILTERS:
            button = ttk.Radiobutton(toolbar, text=view, variable=active, value=view,
                                     command=lambda view=view: display(view))
            button.pack(side=tk.LEFT)
            window.update()
            button.invoke()
            window.update()
            if (not button.instate(["selected"]) or not entries.winfo_viewable()
                    or any(entries.bbox(index) is None for index in range(entries.size()))):
                raise RuntimeError("Le filtre ou l’une des lignes s’affiche mal.")
            observed[view] = list(entries.get(0, tk.END))
            intact &= snapshot(database) == initial
    finally:
        window.destroy()
    return encode_oracle(expected, observed, intact)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
