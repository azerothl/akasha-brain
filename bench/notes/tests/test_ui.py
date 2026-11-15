"""Parcours bureau : sélectionner une note ré-affiche titre + contenu.

Trou trouvé par la baseline humaine du 2026-11-14 : sans gestionnaire de
sélection, le contenu persisté n'était pas vérifiable par l'UI (seul le
contrôle indépendant tranchait). Repli `skip` sans affichage disponible.
"""

from contextlib import closing
import sqlite3
import tkinter as tk

import pytest

from notes_app import NotesApp
from notes_store import SCHEMA


def test_select_redisplays_content(tmp_path):
    db = tmp_path / "notes.db"
    notes = [
        ("Café — été", "première ligne\ndeuxième ligne"),
        ("Autre note", "contenu distinct"),
    ]
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(SCHEMA)
        conn.executemany("INSERT INTO notes (title, content) VALUES (?, ?)", notes)

    try:
        app = NotesApp(str(db))
    except tk.TclError:
        pytest.skip("pas d'affichage disponible")
    try:
        app.withdraw()
        app.update_idletasks()
        app.title_var.set("Saisie en cours")
        app.content_text.insert("1.0", "Le formulaire doit être remplacé.")

        for index in (1, 0):
            app.notes_list.selection_clear(0, tk.END)
            app.notes_list.selection_set(index)
            app.notes_list.event_generate("<<ListboxSelect>>", when="now")

            title, content = notes[index]
            assert app.title_var.get() == title
            assert app.content_text.get("1.0", "end-1c") == content
    finally:
        app.destroy()
        app.store.close()
