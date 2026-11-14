"""Banc tâches (variante de transfert, réservée) — stockage (version fautive figée).

État initial figé (spec §12.3) :
  1. « Préparer la réunion » — à faire (todo)
  2. « Envoyer la facture » — terminée (done)

Faute volontaire : `list_tasks("todo")` renvoie TOUTES les tâches au lieu
des seules tâches à faire. Les autres filtres sont corrects.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


SCHEMA = (
    "CREATE TABLE IF NOT EXISTS tasks ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "title TEXT NOT NULL, "
    "status TEXT NOT NULL CHECK (status IN ('todo', 'done')))"
)

SEED: tuple[tuple[str, str], ...] = (
    ("Préparer la réunion", "todo"),
    ("Envoyer la facture", "done"),
)


@dataclass
class Task:
    id: int
    title: str
    status: str


class TaskStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(SCHEMA)
        cur = self._conn.execute("SELECT COUNT(*) FROM tasks")
        if cur.fetchone()[0] == 0:
            self._conn.executemany(
                "INSERT INTO tasks (title, status) VALUES (?, ?)", SEED
            )
            self._conn.commit()

    def list_tasks(self, task_filter: str = "all") -> list[Task]:
        """Filtres : 'todo' (« À faire »), 'done' (« Terminées »), 'all »
        (« Toutes »). FAUTE : le filtre 'todo' renvoie tout."""
        if task_filter == "todo":
            rows = self._conn.execute(
                "SELECT id, title, status FROM tasks ORDER BY id"
            ).fetchall()
        elif task_filter == "done":
            rows = self._conn.execute(
                "SELECT id, title, status FROM tasks WHERE status = 'done' ORDER BY id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, title, status FROM tasks ORDER BY id"
            ).fetchall()
        return [Task(id=r[0], title=r[1], status=r[2]) for r in rows]

    def close(self) -> None:
        self._conn.close()
