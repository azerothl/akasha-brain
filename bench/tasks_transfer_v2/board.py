"""Tableau des tâches du scénario réservé, avec un filtre fautif."""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tkinter as tk
from tkinter import ttk

LABELS = ("À faire", "Terminées", "Toutes")
FILTER_VALUES = (None, 1, None)


class TasksBoard(tk.Tk):
    def __init__(self, database: Path) -> None:
        super().__init__()
        self.title("Tableau des tâches")
        self.database = database.resolve().as_uri() + "?mode=ro"
        self.selector = ttk.Combobox(self, values=LABELS, state="readonly")
        self.selector.pack(padx=12, pady=12)
        self.entries = tk.Listbox(self, width=46, height=6)
        self.entries.pack(padx=12, pady=(0, 12))
        self.selector.bind("<<ComboboxSelected>>", self.refresh)
        self.selector.current(0)
        self.refresh()

    def refresh(self, _event=None) -> None:
        value = FILTER_VALUES[self.selector.current()]
        query = "SELECT title FROM work_items WHERE (? IS NULL OR closed = ?) ORDER BY id"
        with closing(sqlite3.connect(self.database, uri=True)) as db:
            titles = db.execute(query, (value, value)).fetchall()
        self.entries.delete(0, tk.END)
        self.entries.insert(tk.END, *(title for (title,) in titles))


if __name__ == "__main__":
    TasksBoard(Path(sys.argv[1])).mainloop()
