"""Compare l’écran de développement à des listes fixées et vérifie SQLite."""

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
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    return rows, sha256(database.read_bytes()).hexdigest()


def priority_key(row: tuple) -> tuple:
    return -row[3], row[6] is None, row[6] or 0, row[0]


def group(row: tuple) -> int:
    if row[2] != "open":
        return 2
    return 0 if row[6] is not None and row[6] <= 7 else 1


def reference(rows: list[tuple], view: str, profile: str) -> list:
    if view == "Terminées":
        selected = [row for row in rows if row[2] == "closed"]
    elif view == "À faire":
        selected = [row for row in rows if row[2] == "open"]
        if profile == "dispatch":
            selected = [row for row in selected if (row[5] is None or row[5] <= 12)
                        and (row[3] == 5 or row[4] is None and row[3] >= 2)]
            selected.sort(key=priority_key)
    else:
        selected = sorted(rows, key=lambda row: (group(row), *priority_key(row))) if profile == "planning" else rows
    return [(row[0], row[1]) for row in selected]


def main(phase: str, module: Path, work: Path) -> int:
    fixture = json.loads((ROOT / "state.json").read_bytes())
    database = work / "development.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        connection.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)", fixture["rows"])
    rows, checksum = snapshot(database)
    assert rows == [tuple(row) for row in fixture["rows"]]
    titles = {row[0]: row[1] for row in rows}
    expected = {view: [f"{job_id} | {titles[job_id]}" for job_id in fixture["visible_ids"][view]] for view in FILTERS}

    window = tk.Tk()
    window.title("Tâches de développement")
    toolbar = ttk.Frame(window)
    toolbar.pack(padx=12, pady=12)
    selection = tk.StringVar(window)
    entries = tk.Listbox(window, height=10, width=54)
    entries.pack(padx=12, pady=(0, 12))

    def display(view: str) -> None:
        if phase == "reference":
            selected = reference(rows, view, fixture["id"])
        else:
            process = subprocess.run([sys.executable, "-B", str(module), str(database), view],
                                     cwd=work, capture_output=True, encoding="utf-8", check=True, timeout=8,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            selected = json.loads(process.stdout)
        entries.delete(0, tk.END)
        entries.insert(tk.END, *(f"{job_id} | {title}" for job_id, title in selected))

    observed = {}
    intact = True
    try:
        # Une erreur du programme de sélection doit remonter au vérificateur.
        def raise_callback(_type, value, traceback):
            raise value.with_traceback(traceback)

        window.report_callback_exception = raise_callback
        window.update()
        for view in FILTERS:
            button = ttk.Radiobutton(toolbar, text=view, value=view, variable=selection,
                                     command=lambda view=view: display(view))
            button.pack(side=tk.LEFT)
            window.update()
            button.invoke()
            window.update()
            if (not button.instate(["selected"]) or not entries.winfo_viewable()
                    or any(entries.bbox(index) is None for index in range(entries.size()))):
                raise RuntimeError("Le filtre ou l’une de ses lignes n’est pas visible.")
            observed[view] = list(entries.get(0, tk.END))
            intact &= snapshot(database) == (rows, checksum)
    finally:
        window.destroy()
    return encode_oracle(expected, observed, intact)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
