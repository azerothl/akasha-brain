from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from akasha_brain.conversation_planning import compile_local_plan, load_conversation_catalog
from akasha_brain.conversation_sessions import GlobalMemoryRef, SessionStore


def test_session_reopens_only_its_project_and_facts(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    second_project = tmp_path / "second-project"
    second_project.mkdir()
    store = SessionStore(tmp_path / "runs/sessions.sqlite")
    first, second = store.create(), store.create()
    store.bind_project(first, project)
    store.bind_project(second, project)
    store.bind_project(second, second_project)
    store.remember(first, "summary_depth", "detailed")
    store.remember(second, "summary_depth", "standard")
    store.remember(second, "project_test", "script", project=second_project)
    reference = GlobalMemoryRef(uuid4())
    store.link_global(first, reference)

    reopened = SessionStore(store.path)
    assert reopened.list() == ((first, 1), (second, 2))
    left, right = reopened.open(first), reopened.open(second)
    assert left.projects == (project,)
    assert set(right.projects) == {project, second_project}
    assert left.active_project == project and right.active_project == second_project
    assert left.global_memory == reference and right.global_memory is None
    assert [(fact.kind, fact.value) for fact in left.facts] == [("summary_depth", "detailed")]
    assert [(fact.kind, fact.value) for fact in right.facts] == [
        ("project_test", "script"), ("summary_depth", "standard"),
    ]


def test_closed_session_admission_rejects_free_text_and_expiration_purges_facts(tmp_path):
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    store = SessionStore(tmp_path / "sessions.sqlite", clock=lambda: now)
    session = store.create()
    token = "AKASHA_G1_SYNTHETIC_SECRET_62b7539d"
    with pytest.raises(ValueError, match="schéma"):
        store.remember(session, "summary_depth", token)
    with pytest.raises(ValueError, match="schéma"):
        store.remember(session, "raw_prompt", token)
    with pytest.raises(ValueError, match="registre"):
        store.bind_project(session, tmp_path)
    store.remember(session, "summary_depth", "detailed")
    original = store.open(session).facts[0]
    now = original.expires_at - timedelta(seconds=1)
    assert store.open(session).facts == (original,)
    now = original.expires_at
    assert store.open(session).facts == ()
    now = original.created_at
    assert store.open(session).facts == ()
    for path in tmp_path.iterdir():
        payload = path.read_bytes()
        assert token.encode() not in payload
        assert sha256(token.encode()).hexdigest().encode() not in payload


def test_project_binding_detects_moved_or_replaced_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = SessionStore(tmp_path / "runs/sessions.sqlite")
    session = store.create()
    store.bind_project(session, project)
    store.remember(session, "project_test", "script", project=project)
    moved = tmp_path / "moved"
    project.rename(moved)
    project.mkdir()

    reopened = store.open(session)
    assert not reopened.projects and reopened.active_project is None and not reopened.facts
    with pytest.raises(ValueError, match="hors de la session"):
        store.remember(session, "project_test", "script", project=project)


@pytest.mark.parametrize(("wording", "preference", "expected"), [
    ("Présente ce projet", "standard", "overview"),
    ("Présente ce projet", "detailed", "detailed"),
    ("Fais un résumé court de ce projet", "detailed", "overview"),
    ("Fais un résumé détaillé de ce projet", "standard", "detailed"),
])
def test_session_summary_preference_is_used_as_a_default(wording, preference, expected):
    plan = compile_local_plan(wording, "project.summarize", ("C:/example",), load_conversation_catalog(),
                              default_summary_depth=preference)
    assert plan.goal["constraints"]["summary_depth"] == expected
