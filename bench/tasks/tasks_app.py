"""Banc tâches (variante de transfert, réservée) — interface tkinter.

Le sélecteur de filtre appelle `TaskStore.list_tasks` : sur la version
fautive, « À faire » affiche aussi les tâches terminées.
Usage : `python tasks_app.py [chemin.db]`.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from tasks_store import TaskStore

DEFAULT_DB = "tasks.db"
FILTERS = {"À faire": "todo", "Terminées": "done", "Toutes": "all"}


class TasksApp(tk.Tk):
    def __init__(self, db_path: str = DEFAULT_DB) -> None:
        super().__init__()
        self.title("Tâches — banc Akasha (transfert)")
        self.store = TaskStore(db_path)

        self.filter_var = tk.StringVar(value="À faire")
        ttk.Label(self, text="Filtre :").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.filter_box = ttk.Combobox(
            self, textvariable=self.filter_var, values=list(FILTERS), state="readonly"
        )
        self.filter_box.grid(row=0, column=1, padx=8, pady=4)
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())

        self.tasks_list = tk.Listbox(self, width=60, height=8)
        self.tasks_list.grid(row=1, column=0, columnspan=2, padx=8, pady=4)
        self.refresh_list()

    def refresh_list(self) -> None:
        self.tasks_list.delete(0, tk.END)
        for task in self.store.list_tasks(FILTERS[self.filter_var.get()]):
            mark = "[x]" if task.status == "done" else "[ ]"
            self.tasks_list.insert(tk.END, f"{mark} {task.title}")


def main(argv: list[str]) -> None:
    db_path = argv[1] if len(argv) > 1 else DEFAULT_DB
    app = TasksApp(db_path)
    app.mainloop()


if __name__ == "__main__":
    main(sys.argv)
