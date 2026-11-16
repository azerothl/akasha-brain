"""Tableau Tk des échéances et des différentes sélections."""

import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

VIEWS = {"À faire": "pending", "Terminées": "closed", "Toutes": "all"}


class DeadlineBoard(tk.Tk):
    def __init__(self, module: Path, database: Path) -> None:
        super().__init__()
        self.title("Tableau des échéances")
        self.module = module
        self.database = database
        controls = ttk.Frame(self)
        controls.pack(padx=10, pady=10)
        self.buttons = {}
        for label in VIEWS:
            button = ttk.Button(controls, text=label, command=lambda name=label: self.select(name))
            button.pack(side="left", padx=4)
            self.buttons[label] = button
        self.selection = tk.StringVar()
        ttk.Label(self, textvariable=self.selection).pack()
        self.rows = tk.Listbox(self, width=55, height=9)
        self.rows.pack(padx=10, pady=10)

    def select(self, name: str) -> None:
        self.selection.set(name)
        self.rows.delete(0, tk.END)
        call = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.module), str(self.database), VIEWS[name]],
            cwd=self.database.parent, capture_output=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=6,
        )
        self.rows.insert(tk.END, *(f"{task_id} | {title}" for task_id, title in json.loads(call.stdout)))
