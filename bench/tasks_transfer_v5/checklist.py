"""Tableau des listes de contrôle, avec sélection en processus séparé."""

import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

VIEWS = {"À faire": "pending", "Terminées": "closed", "Toutes": "all"}


class Checklist(tk.Tk):
    def __init__(self, module: Path, database: Path) -> None:
        super().__init__()
        self.title("Tableau des listes de contrôle")
        self.module = module
        self.database = database
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(padx=12, pady=12)
        self.lists = {}
        for label in VIEWS:
            page = ttk.Frame(self.tabs)
            rows = tk.Listbox(page, width=52, height=8)
            rows.pack(padx=8, pady=8)
            self.tabs.add(page, text=label)
            self.lists[label] = rows
        self.tabs.bind("<<NotebookTabChanged>>", self.refresh)

    def refresh(self, _event=None) -> None:
        label = self.tabs.tab(self.tabs.select(), "text")
        rows = self.lists[label]
        rows.delete(0, tk.END)
        run = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.module), str(self.database), VIEWS[label]],
            cwd=self.database.parent, capture_output=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=6,
        )
        rows.insert(tk.END, *(f"{task_id} | {title}" for task_id, title in json.loads(run.stdout)))
