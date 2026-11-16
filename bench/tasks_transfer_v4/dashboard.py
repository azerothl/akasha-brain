"""Tableau Tk dont le processus de sélection est séparé de l'affichage."""

import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

LABELS = ("À faire", "Terminées", "Toutes")
VIEWS = ("pending", "closed", "all")


class Dashboard(tk.Tk):
    def __init__(self, module: Path, database: Path) -> None:
        super().__init__()
        self.module = module
        self.database = database
        self.title("Suivi des tâches et réouvertures")
        controls = ttk.Frame(self)
        controls.pack(padx=12, pady=12)
        self.selection = tk.StringVar(value=VIEWS[0])
        self.buttons = {}
        for label, view in zip(LABELS, VIEWS):
            button = ttk.Radiobutton(controls, text=label, value=view, variable=self.selection, command=self.refresh)
            button.pack(side="left", padx=6)
            self.buttons[label] = button
        self.entries = tk.Listbox(self, width=54, height=8)
        self.entries.pack(padx=12, pady=(0, 12))
        self.refresh()

    def refresh(self) -> None:
        self.entries.delete(0, tk.END)
        run = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.module), str(self.database), self.selection.get()],
            cwd=self.database.parent, capture_output=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=6,
        )
        rows = json.loads(run.stdout)
        self.entries.insert(tk.END, *(f"{item_id} | {title}" for item_id, title in rows))
