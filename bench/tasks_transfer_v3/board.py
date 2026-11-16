"""Interface Tk du tableau, séparée du module de sélection."""

import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

LABELS = ("À faire", "Terminées", "Toutes")
VIEWS = ("pending", "closed", "all")


class Board(tk.Tk):
    def __init__(self, selection: Path, database: Path) -> None:
        super().__init__()
        self.title("Tableau de suivi")
        self.selection = selection
        self.database = database
        self.selector = ttk.Combobox(self, values=LABELS, state="readonly")
        self.selector.pack(padx=12, pady=12)
        self.entries = tk.Listbox(self, width=52, height=8)
        self.entries.pack(padx=12, pady=(0, 12))
        self.selector.bind("<<ComboboxSelected>>", self.refresh)
        self.selector.current(0)
        self.refresh()

    def refresh(self, _event=None) -> None:
        self.entries.delete(0, tk.END)
        view = VIEWS[self.selector.current()]
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.selection), str(self.database), view],
            cwd=self.database.parent, capture_output=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=6,
        )
        rows = json.loads(result.stdout)
        self.entries.insert(tk.END, *(f"{item_id} | {title}" for item_id, title in rows))
