"""Banc notes — vérificateur indépendant (spec §12.3).

Rejoue le scénario de référence (saisie → sauvegarde → fermeture réelle →
réouverture sur le même stockage) puis contrôle l'état persisté par lecture
SQLite directe, sans passer par `NoteStore` : c'est ce contrôle, et non
l'affichage de l'UI ni un modèle, qui détermine la réussite.

Usage :
    python verify_notes.py --db <chemin.db> [--reset]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notes_store import NoteStore

EXPECTED_TITLE = "Note de vérification"
EXPECTED_CONTENT = "Contenu exact — accents éèê\ndeuxième ligne"


def reset(db_path: str) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
    store = NoteStore(db_path)
    store.close()


def read_persisted(db_path: str) -> list[tuple[str, str]]:
    """Lecture indépendante : SQL brut, pas de NoteStore."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT title, content FROM notes ORDER BY id").fetchall()
    finally:
        conn.close()
    return [(r[0], r[1]) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="notes_check.db")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset or not os.path.exists(args.db):
        reset(args.db)

    # Parcours : saisie + sauvegarde via le même appel que l'UI.
    store = NoteStore(args.db)
    store.save_note(EXPECTED_TITLE, EXPECTED_CONTENT)
    store.close()  # fermeture réelle du processus logique (connexion fermée)

    # Réouverture sur le même stockage + contrôle indépendant.
    persisted = read_persisted(args.db)
    if (EXPECTED_TITLE, EXPECTED_CONTENT) in persisted:
        print("PASS: la note persiste après fermeture et réouverture.")
        return 0
    print("FAIL: note absente du stockage durable après réouverture.")
    print(f"Contenu persisté observé : {persisted!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
