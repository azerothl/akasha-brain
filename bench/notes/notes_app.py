"""Banc notes — interface tkinter (parcours bureau, Phase 0).

La sauvegarde passe par `NoteStore.save_note` : sur la version fautive,
le statut annonce « Note sauvegardée » alors que rien n'est persisté.
Usage : `python notes_app.py [chemin.db]`.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from notes_store import NoteStore

DEFAULT_DB = "notes.db"


class NotesApp(tk.Tk):
    def __init__(self, db_path: str = DEFAULT_DB) -> None:
        super().__init__()
        self.title("Notes — banc Akasha")
        self.store = NoteStore(db_path)

        self.title_var = tk.StringVar()
        ttk.Label(self, text="Titre :").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(self, textvariable=self.title_var, width=50).grid(
            row=0, column=1, padx=8, pady=4
        )
        ttk.Label(self, text="Contenu :").grid(row=1, column=0, sticky="nw", padx=8, pady=4)
        self.content_text = tk.Text(self, width=50, height=10)
        self.content_text.grid(row=1, column=1, padx=8, pady=4)

        ttk.Button(self, text="Enregistrer", command=self.on_save).grid(
            row=2, column=1, sticky="e", padx=8, pady=4
        )
        self.status_var = tk.StringVar(value="Prêt.")
        ttk.Label(self, textvariable=self.status_var).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=8, pady=4
        )
        self.notes_list = tk.Listbox(self, width=70, height=8)
        self.notes_list.grid(row=4, column=0, columnspan=2, padx=8, pady=4)
        self.refresh_list()

    def on_save(self) -> None:
        title = self.title_var.get()
        content = self.content_text.get("1.0", "end-1c")
        self.store.save_note(title, content)
        self.status_var.set("Note sauvegardée.")
        self.refresh_list()

    def refresh_list(self) -> None:
        self.notes_list.delete(0, tk.END)
        for note in self.store.list_notes():
            self.notes_list.insert(tk.END, f"#{note.id} {note.title}")


def main(argv: list[str]) -> None:
    db_path = argv[1] if len(argv) > 1 else DEFAULT_DB
    app = NotesApp(db_path)
    app.mainloop()


if __name__ == "__main__":
    main(sys.argv)
