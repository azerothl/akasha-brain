"""Tableau Tk avec un processus de sélection distinct par filtre."""

import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

VIEWS = {"À faire": "pending", "Terminées": "closed", "Toutes": "all"}


class Board(tk.Tk):
    def __init__(self, selection: Path, database: Path) -> None:
        super().__init__()
        self.title("Suivi des clôtures")
        self.selection = selection
        self.database = database
        self.view = tk.StringVar(self)
        toolbar = ttk.Frame(self)
        toolbar.pack(padx=12, pady=12)
        self.filters = {}
        for label, value in VIEWS.items():
            button = ttk.Radiobutton(toolbar, text=label, variable=self.view, value=value, command=self.refresh)
            button.pack(side=tk.LEFT, padx=3)
            self.filters[label] = button
        self.entries = tk.Listbox(self, width=54, height=9)
        self.entries.pack(padx=12, pady=(0, 12))

    def refresh(self) -> None:
        self.entries.delete(0, tk.END)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.selection), str(self.database), self.view.get()],
            cwd=self.database.parent, capture_output=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=6,
        )
        self.entries.insert(tk.END, *(f"{task_id} | {title}" for task_id, title in json.loads(result.stdout)))
