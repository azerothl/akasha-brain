from concurrent.futures import Future
from contextlib import closing
from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import socket
import sqlite3
import subprocess
import sys
from time import monotonic
from uuid import UUID

import pytest

from akasha_brain import desktop_conversation, web_collection
from akasha_brain.conversation_planning import references, web_targets
from akasha_brain.desktop_conversation import ConversationPane
from akasha_brain.planning import PlanningError
from contracts.akasha_contracts.errors import ErrorCode


CHANNEL = "https://www.youtube.com/@sandboxfr"
REQUEST = f"est ce que tu peux analyser ma chaine youtube {CHANNEL} et me faire des recommandations ?"
FOLLOWUP = "tu ne peux pas regarder les stats de vue directement sur le lien de la chaine ?"


def test_urls_keep_handle_path_query_and_remain_distinct_from_local_files():
    assert web_targets(REQUEST, ()) == (CHANNEL,)
    assert web_targets(FOLLOWUP, (CHANNEL,)) == (CHANNEL,)
    assert web_targets(FOLLOWUP, ()) == ()
    assert web_targets("Vérifie mon projet", (CHANNEL,)) == ()
    link = "https://example.org/un%20lien(a)?q=abc%3F&other=value#part"
    assert web_targets(f"Lis [guide.md]({link}).", ()) == (link,)
    assert references(f'Lis "notes.txt" ou {link}.') == ["notes.txt"]
    assert web_targets(f"{CHANNEL} ou {link}", ()) == (CHANNEL, link)


def test_desktop_confirms_before_collecting_and_reuses_url_only_in_current_pane(tmp_path, monkeypatch):
    collected = Mock(side_effect=lambda target: web_collection.Observation(
        target.url, datetime.now(timezone.utc).isoformat(), "Un titre public.", False))
    monkeypatch.setattr(web_collection, "bounded_read", collected)
    monkeypatch.setattr(desktop_conversation, "app_directory", lambda: tmp_path)

    def ready(operation):
        future = Future()
        future.set_result(operation())
        return future

    def new_pane():
        pane = ConversationPane.__new__(ConversationPane)
        pane.entry = Mock()
        pane.confirm = Mock()
        pane.tasks = SimpleNamespace(scheduler=SimpleNamespace(submit=ready))
        pane.add = Mock()
        pane.seal_request = lambda request: False
        pane.show_capabilities = Mock()
        pane.project = pane.intent_job = pane.audio_decision = pane.last_summary_project = None
        pane.communication = pane.project_job = pane.check_job = pane.pending_intent = pane.change = None
        pane.web_urls = ()
        return pane

    pane = new_pane()
    pane.entry.get.return_value = REQUEST
    pane.pending_intent = ("Vérifie le projet", 1)
    pane.send()
    assert pane.pending_intent is None
    assert pane.pending_web.target.url == CHANNEL
    assert pane.action == "read_web"
    collected.assert_not_called()
    pane.confirm_action()
    pane.poll_intent()
    collected.assert_called_once_with(web_collection.public_target(CHANNEL))
    assert pane.add.call_args.args[0] == "Texte public relevé"
    assert "Un titre public." in pane.add.call_args.args[1]
    assert "dossier" not in str(pane.add.call_args_list)

    pane.entry.get.return_value = FOLLOWUP
    pane.send()
    assert pane.pending_web.target.url == CHANNEL
    collected.assert_called_once()
    pane.entry.get.return_value = "Annuler"
    pane.send()
    assert pane.pending_web is None
    collected.assert_called_once()

    pane.project = tmp_path
    pane.entry.get.return_value = f'Remplace "{CHANNEL}" par "nouveau" dans article.md'
    pane.send()
    assert pane.change.before == CHANNEL
    assert pane.pending_web is None

    other = new_pane()
    other.entry.get.return_value = FOLLOWUP
    other.send()
    assert other.pending_web is None
    assert other.web_urls == ()
    collected.assert_called_once()


def test_consent_is_required_expires_and_is_consumed_without_logging_url(tmp_path, monkeypatch):
    database = tmp_path / "audit.sqlite"
    target = web_collection.public_target("https://example.org/private-path?key=sensitive")
    collect = Mock(return_value="observation")
    monkeypatch.setattr(web_collection, "bounded_read", collect)
    review = web_collection.ReadReview(target)
    expired = web_collection.ReadReview(target, expires_at=0)

    with pytest.raises(PlanningError) as denied:
        review.collect(database, approved=False, cancelled=lambda: False)
    assert denied.value.error.code == ErrorCode.APPROVAL_REQUIRED
    with pytest.raises(PlanningError) as late:
        expired.collect(database, approved=True, cancelled=lambda: False)
    assert late.value.error.code == ErrorCode.APPROVAL_EXPIRED
    collect.assert_not_called()

    assert review.collect(database, approved=True, cancelled=lambda: False) == "observation"
    with pytest.raises(PlanningError) as spent:
        review.collect(database, approved=True, cancelled=lambda: False)
    assert spent.value.error.code == ErrorCode.GRANT_BUDGET_EXHAUSTED
    collect.assert_called_once_with(target)
    with closing(sqlite3.connect(database)) as connection:
        cursor = connection.execute("SELECT * FROM web_audit ORDER BY seq")
        assert [column[0] for column in cursor.description] == ["seq", "request_id", "created_at", "outcome"]
        rows = cursor.fetchall()
    assert [(key, status) for _, key, _, status in rows] == [
        (review.request_id, "approval_required"), (expired.request_id, "approval_expired"),
        (review.request_id, "authorized"), (review.request_id, "collected"),
        (review.request_id, "grant_budget_exhausted")]
    for seq, key, stamp, _ in rows:
        assert isinstance(seq, int) and str(UUID(key)) == key
        assert datetime.fromisoformat(stamp).tzinfo == timezone.utc
    assert b"example.org" not in database.read_bytes()
    assert b"sensitive" not in database.read_bytes()


@pytest.mark.parametrize("url", ["http://example.org", "https://user@example.org", "https://example.org:444",
                                "https://127.0.0.1", "https://[::1]", "https://localhost"])
def test_public_target_rejects_unsupported_destinations(url):
    with pytest.raises(PlanningError) as error:
        web_collection.public_target(url)
    assert error.value.error.code == ErrorCode.PERMISSION_DENIED


def test_mixed_dns_results_stop_before_opening_socket(monkeypatch):
    dns = Mock(return_value=[(None, None, None, None, ("8.8.8.8", 443)),
                             (None, None, None, None, ("10.0.0.1", 443))])
    connect = Mock()
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(socket, "create_connection", connect)
    connection = web_collection.PublicConnection("example.org", port=443, timeout=5)
    with pytest.raises(PlanningError) as error:
        connection.connect()
    assert error.value.error.code == ErrorCode.PERMISSION_DENIED
    dns.assert_called_once_with("example.org.", 443, type=socket.SOCK_STREAM)
    connect.assert_not_called()


def test_tls_checks_original_host_on_pinned_address(monkeypatch):
    tcp = Mock()
    connect = Mock(return_value=tcp)
    context = Mock()
    monkeypatch.setattr(web_collection, "public_address", lambda host: "8.8.8.8")
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(web_collection.ssl, "SSLContext", lambda protocol: context)
    connection = web_collection.PublicConnection("example.org", port=443, timeout=5)
    connection.connect()
    context.load_default_certs.assert_called_once()
    connect.assert_called_once_with(("8.8.8.8", 443), 5)
    context.wrap_socket.assert_called_once_with(tcp, server_hostname="example.org")


class Reply(BytesIO):
    def __init__(self, raw, status=200, content_type="text/html; charset=utf-8"):
        super().__init__(raw)
        self.status = status
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        self.read = Mock(wraps=self.read)


@pytest.fixture
def connection(monkeypatch):
    connection = Mock()
    monkeypatch.setattr(web_collection, "PublicConnection", lambda *args, **kwargs: connection)
    return connection


def test_broker_extracts_static_text_and_stops_at_redirect(connection):
    target = web_collection.public_target("https://example.org/docs?q=yes#section")
    connection.getresponse.return_value = Reply(b"<h1>Article</h1><script>hidden()</script>", 200)
    assert web_collection.read_public_text(target)["text"] == "Article"
    request = connection.request.call_args
    assert request.args == ("GET", "/docs?q=yes")
    assert "Authorization" not in request.kwargs["headers"]
    assert "Cookie" not in request.kwargs["headers"]

    connection.request.reset_mock()
    connection.getresponse.return_value = Reply(b"", 302)
    connection.getresponse.return_value.headers["Location"] = "https://other.example/"
    with pytest.raises(PlanningError) as redirect:
        web_collection.read_public_text(target)
    assert redirect.value.error.code == ErrorCode.PERMISSION_DENIED
    assert connection.request.call_count == 1


@pytest.mark.parametrize("length", [262143, 262144, 262145, 262200])
def test_body_limit_reads_only_one_detection_byte(length, connection):
    page = Reply(b"Article" + b" " * (length - 7), content_type="text/plain")
    connection.getresponse.return_value = page
    result = web_collection.read_public_text(web_collection.public_target("https://example.com/"))
    page.read.assert_called_once_with(262145)
    assert (result["text"], result["truncated"]) == ("Article", length > 262144)


@pytest.mark.parametrize("length", [7999, 8000, 8001])
def test_excerpt_limit_counts_characters(length, connection):
    connection.getresponse.return_value = Reply(("é" * length).encode(), content_type="text/markdown")
    result = web_collection.read_public_text(web_collection.public_target("https://example.com/"))
    assert (result["text"], result["truncated"]) == ("é" * min(length, 8000), length > 8000)


@pytest.mark.parametrize(("content_type", "encoding"), [
    (None, "identity"), ("", "identity"), ("image/png", "identity"), ("text/html", "gzip"),
])
def test_requires_supported_response_before_reading_body(content_type, encoding, connection):
    page = Reply(b"ordinary response", content_type=content_type)
    page.headers["Content-Encoding"] = encoding
    connection.getresponse.return_value = page
    with pytest.raises(PlanningError) as refused:
        web_collection.read_public_text(web_collection.public_target("https://example.com/"))
    assert refused.value.error.code == ErrorCode.CAPABILITY_UNAVAILABLE
    page.read.assert_not_called()


def test_five_minute_approval_boundary(tmp_path, monkeypatch):
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr(web_collection, "monotonic", clock)
    fetch = Mock(return_value="ok")
    monkeypatch.setattr(web_collection, "bounded_read", fetch)
    target = web_collection.public_target("https://example.com/")
    valid, expired = web_collection.ReadReview(target), web_collection.ReadReview(target)
    db = tmp_path / "audit.sqlite"
    clock.return_value = 1299.999
    assert valid.collect(db, approved=True, cancelled=lambda: False) == "ok"
    clock.return_value = 1300.0
    with pytest.raises(PlanningError) as late:
        expired.collect(db, approved=True, cancelled=lambda: False)
    assert late.value.error.code == ErrorCode.APPROVAL_EXPIRED
    fetch.assert_called_once_with(target)


def test_wall_deadline_stops_local_worker_and_spends_approval(tmp_path, monkeypatch):
    # L’enfant local attend sans réseau. Le parent garde son horloge et son plafond de production.
    popen = subprocess.Popen
    workers = []

    def slow_worker(_command, **kwargs):
        worker = popen([sys.executable, "-c", "import time; time.sleep(45)"], **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(subprocess, "Popen", slow_worker)
    assert web_collection.TIMEOUT == 15
    review = web_collection.ReadReview(web_collection.public_target("https://example.com/"))
    db = tmp_path / "audit.sqlite"
    start = monotonic()
    with pytest.raises(PlanningError) as timed_out:
        review.collect(db, approved=True, cancelled=lambda: False)
    assert 15 <= monotonic() - start < 45
    assert timed_out.value.error.code == ErrorCode.TIMEOUT_EXCEEDED
    with pytest.raises(PlanningError) as spent:
        review.collect(db, approved=True, cancelled=lambda: False)
    assert spent.value.error.code == ErrorCode.GRANT_BUDGET_EXHAUSTED
    assert len(workers) == 1 and workers[0].poll() is not None
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT outcome FROM web_audit ORDER BY seq").fetchall() == [
            ("authorized",), ("timeout_exceeded",), ("grant_budget_exhausted",)]
