"""Action Tk fixe et sonde SQLite indépendante pour le banc DesktopState."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

TITLE = "Note DesktopState"
CONTENT = "Contenu durable du banc Notes"
SAVE_STATUS = "Note sauvegardée."
SQLITE_EMPTY = 0x4650
SQLITE_FIXTURE = 0x4651
SQLITE_MISMATCH = 0x4652


def open_notes(database: Path) -> None:
    from tkinter import ttk

    from notes_app import NotesApp

    app = NotesApp(str(database))
    save_button, = (widget for widget in app.winfo_children() if isinstance(widget, ttk.Button))
    request = database.with_name("save.request")

    def save_on_request():
        if not request.is_file():
            app.after(40, save_on_request)
            return
        app.title_var.set(TITLE)
        app.content_text.insert("1.0", CONTENT)
        save_button.invoke()
        if (app.status_var.get() == SAVE_STATUS and app.notes_list.size() == 1
                and app.notes_list.get(0).endswith(f" {TITLE}")):
            request.with_suffix(".done").touch(exist_ok=False)

    app.after(40, save_on_request)
    app.mainloop()


def check_sqlite(database: Path) -> int:
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            return SQLITE_MISMATCH
        rows = db.execute("SELECT title, content FROM notes LIMIT 2").fetchall()
    if not rows:
        return SQLITE_EMPTY
    return SQLITE_FIXTURE if rows == [(TITLE, CONTENT)] else SQLITE_MISMATCH


if __name__ == "__main__":
    command, db_path = sys.argv[1:]
    if command == "open":
        open_notes(Path(db_path))
    elif command == "sqlite":
        raise SystemExit(check_sqlite(Path(db_path)))
    else:
        raise SystemExit(2)
