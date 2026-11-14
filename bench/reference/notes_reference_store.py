"""RÉFÉRENCE SCELLÉE — correction du banc notes (contrôle/baseline uniquement).

Même interface que `bench/notes/notes_store.py`, mais `save_note` persiste
réellement (INSERT + commit). Ne jamais fournir aux candidats (voir README).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


SCHEMA = (
    "CREATE TABLE IF NOT EXISTS notes ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "title TEXT NOT NULL, "
    "content TEXT NOT NULL)"
)


@dataclass
class Note:
    id: int
    title: str
    content: str


class NoteStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def save_note(self, title: str, content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO notes (title, content) VALUES (?, ?)", (title, content)
        )
        self._conn.commit()
        return cur.lastrowid

    def list_notes(self) -> list[Note]:
        cur = self._conn.execute("SELECT id, title, content FROM notes ORDER BY id")
        return [Note(id=row[0], title=row[1], content=row[2]) for row in cur.fetchall()]

    def get_note(self, note_id: int) -> Note | None:
        for note in self.list_notes():
            if note.id == note_id:
                return note
        return None

    def close(self) -> None:
        self._conn.close()
