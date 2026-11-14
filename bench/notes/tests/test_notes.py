"""Banc notes — régression et non-régressions (spec §12.3).

Sur la version fautive figée, les tests de persistance ÉCHOUENT : c'est le
comportement attendu du banc (échec initial à reproduire puis corriger).
`test_save_acknowledged_in_session` caractérise le succès annoncé en session.
"""

from __future__ import annotations

from notes_store import NoteStore


def _reopen(db_path) -> NoteStore:
    """Nouvelle instance = redémarrage de l'application (cache vidé)."""
    return NoteStore(str(db_path))


def test_saved_note_survives_restart(tmp_path):
    """Régression : le contenu exact réapparaît après redémarrage."""
    db = tmp_path / "notes.db"
    store = NoteStore(str(db))
    store.save_note("Ma note", "Contenu exact à retrouver")
    store.close()

    reopened = _reopen(db)
    try:
        contents = [n.content for n in reopened.list_notes()]
    finally:
        reopened.close()
    assert contents == ["Contenu exact à retrouver"]


def test_two_notes_with_accents_multiline_survive_restart(tmp_path):
    """Non-régression : deux notes distinctes, accents + multiligne."""
    db = tmp_path / "notes.db"
    store = NoteStore(str(db))
    store.save_note("Café — été", "première ligne\ndeuxième ligne\ntroisième ligne")
    store.save_note("Simple", "texte brut")
    store.close()

    reopened = _reopen(db)
    try:
        contents = [n.content for n in reopened.list_notes()]
    finally:
        reopened.close()
    assert contents == [
        "première ligne\ndeuxième ligne\ntroisième ligne",
        "texte brut",
    ]


def test_save_acknowledged_in_session(tmp_path):
    """La note est visible en session aussitôt après « Enregistrer »."""
    db = tmp_path / "notes.db"
    store = NoteStore(str(db))
    try:
        store.save_note("Brouillon", "visible tout de suite")
        titles = [n.title for n in store.list_notes()]
    finally:
        store.close()
    assert titles == ["Brouillon"]
