"""Banc tâches (variante de transfert, réservée) — vérificateur indépendant.

Sélectionne chaque filtre via le même appel que l'UI (`TaskStore.list_tasks`),
puis contrôle les éléments visibles par lecture SQLite directe (indépendante
de l'OCR et de la méthode filtrante). Usage :
    python verify_tasks.py --db <chemin.db> [--reset]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks_store import SEED, TaskStore

EXPECTED = {
    "todo": ["Préparer la réunion"],
    "done": ["Envoyer la facture"],
    "all": ["Préparer la réunion", "Envoyer la facture"],
}


def reset(db_path: str) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
    store = TaskStore(db_path)
    store.close()


def read_all_raw(db_path: str) -> list[tuple[str, str]]:
    """Lecture indépendante : SQL brut, pas de TaskStore."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT title, status FROM tasks ORDER BY id").fetchall()
    finally:
        conn.close()
    return [(r[0], r[1]) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="tasks_check.db")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset or not os.path.exists(args.db):
        reset(args.db)

    # Garde-fou : l'état initial figé n'a pas dérivé.
    if read_all_raw(args.db) != list(SEED):
        print(f"FAIL: état initial inattendu : {read_all_raw(args.db)!r}")
        return 1

    store = TaskStore(args.db)
    try:
        shown = {
            name: [t.title for t in store.list_tasks(name)] for name in EXPECTED
        }
        states_after = read_all_raw(args.db)
    finally:
        store.close()

    failures = [
        f"filtre {name!r} : observé {shown[name]!r}, attendu {EXPECTED[name]!r}"
        for name in EXPECTED
        if shown[name] != EXPECTED[name]
    ]
    if states_after != list(SEED):
        failures.append(f"les états ont changé pendant le filtrage : {states_after!r}")

    if failures:
        print("FAIL:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PASS: chaque filtre montre les éléments attendus, états inchangés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
