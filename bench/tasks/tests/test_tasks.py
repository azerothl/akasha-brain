"""Banc tâches (variante de transfert, réservée) — régression et non-régressions.

Sur la version fautive figée, le test de régression ÉCHOUE (faute du filtre
« À faire ») ; les non-régressions passent et bornent la faute.
"""

from __future__ import annotations

from tasks_store import TaskStore


def test_todo_filter_shows_only_todo(tmp_path):
    """Régression : sous « À faire », seule « Préparer la réunion »."""
    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        titles = [t.title for t in store.list_tasks("todo")]
    finally:
        store.close()
    assert titles == ["Préparer la réunion"]


def test_done_filter_shows_only_done(tmp_path):
    """Non-régression : sous « Terminées », seule « Envoyer la facture »."""
    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        titles = [t.title for t in store.list_tasks("done")]
    finally:
        store.close()
    assert titles == ["Envoyer la facture"]


def test_all_filter_shows_both_without_changing_states(tmp_path):
    """Non-régression : « Toutes » montre les deux, sans changer les états."""
    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        shown = [(t.title, t.status) for t in store.list_tasks("all")]
        states_after = [(t.title, t.status) for t in store.list_tasks("all")]
    finally:
        store.close()
    assert shown == [
        ("Préparer la réunion", "todo"),
        ("Envoyer la facture", "done"),
    ]
    assert states_after == shown
