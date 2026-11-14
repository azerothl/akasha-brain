"""Banc notes — couche de stockage SQLite (version fautive figée, Phase 0).

Faute volontaire (spec §12.3) : `save_note` ajoute la note à un cache en
mémoire et renvoie un identifiant, mais n'écrit jamais dans SQLite.
L'interface affiche donc la note et annonce un succès, puis la note
disparaît au redémarrage (nouvelle instance = cache vidé).
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
    """Stockage des notes. Le bug est dans `save_note` (voir docstring module)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(SCHEMA)
        self._conn.commit()
        # Cache de session : ce que l'UI affiche sans persistance.
        self._session_cache: list[Note] = []
        self._next_fake_id = -1

    def save_note(self, title: str, content: str) -> int:
        """Enregistre une note. FAUTE : reste en mémoire, jamais persistée."""
        note = Note(id=self._next_fake_id, title=title, content=content)
        self._next_fake_id -= 1
        self._session_cache.append(note)
        return note.id

    def list_notes(self) -> list[Note]:
        """Notes persistées + notes de session (ce que l'UI affiche)."""
        cur = self._conn.execute("SELECT id, title, content FROM notes ORDER BY id")
        persisted = [Note(id=row[0], title=row[1], content=row[2]) for row in cur.fetchall()]
        return persisted + list(self._session_cache)

    def get_note(self, note_id: int) -> Note | None:
        for note in self.list_notes():
            if note.id == note_id:
                return note
        return None

    def close(self) -> None:
        self._conn.close()
