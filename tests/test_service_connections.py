from datetime import datetime, timedelta, timezone
import json

import pytest

from akasha_brain.conversation_sessions import SessionStore
from akasha_brain.conversation_vault import SessionVault
from akasha_brain.service_connections import Connections
from akasha_brain.service_registry import DEFAULT_REGISTRY, ServiceError, load_registry
from bench.service_test_providers import providers
from tests.test_conversation_vault import TestKeyStore


@pytest.fixture
def setup(tmp_path):
    now = [datetime.now(timezone.utc)]
    sessions = SessionStore(tmp_path / "sessions.sqlite", clock=lambda: now[0])
    backend = TestKeyStore()
    vault = SessionVault(tmp_path, sessions, keystore=lambda: backend)
    session = sessions.create()
    with providers(tmp_path, "synthetic-secret") as fixtures:
        entries = json.loads(DEFAULT_REGISTRY.read_bytes())
        for entry in entries:
            entry["origin"] = fixtures[entry["id"]].origin
        path = tmp_path / "registry.json"
        path.write_text(json.dumps(entries))
        yield Connections(vault, registry_path=path), session, fixtures, backend, now


def create(setup, name="publication-test", **overrides):
    runtime, session, fixtures, _, _ = setup
    fixture = fixtures[name]
    args = dict(origin=fixture.origin, identity="editor" if fixture.token else "public",
                scopes=["publication.read", "publication.publish"] if fixture.token else ["catalogue.status"],
                minutes=1, certificate=fixture.certificate.read_text(),
                secret=bytearray(fixture.token.encode()) if fixture.token else None)
    return runtime.authorize(session, name, **(args | overrides))


def approved_call(runtime, *args, **kwargs):
    return runtime.call(*args, approve_egress=lambda preview: True, **kwargs)


def refuses(code):
    return pytest.raises(ServiceError, match=f"^{code}$")


def test_public_and_authenticated_provenance_and_durable_effect(setup):
    runtime, session, fixtures, backend, _ = setup
    public = create(setup, "catalogue-test")
    result = approved_call(runtime, session, public, "catalogue.status", {})
    assert result["result"] == {"available": True}
    assert result["provenance"]["destination"] == fixtures["catalogue-test"].origin + "/v1/status"
    assert backend.reads == []
    grant = create(setup)
    data = {"document": "demo"}
    with refuses("effect_approval_required"):
        approved_call(runtime, session, grant, "publication.publish", data)
    service = fixtures["publication-test"]
    assert not service.published("demo") and not service.events and not backend.reads
    def approve(preview):
        assert preview["input"] == data and preview["effect"] == "persistent"
        preview["input"]["document"] = "other"
        data["document"] = "other"
        return True
    output = approved_call(runtime, session, grant, "publication.publish", data, approve_effect=approve)
    assert output["result"] == {"published": True}
    assert service.published("demo") and not service.published("other")
    assert len(backend.reads) == len(service.events) == 1
    with refuses("effect_approval_required"):
        approved_call(runtime, session, grant, "publication.publish", data, approve_effect=lambda _: False)
    assert len(service.events) == 1


def test_runtime_boundary_and_least_privilege(setup):
    runtime, session, fixtures, backend, _ = setup
    with refuses("destination_denied"):
        create(setup, origin="https://example.invalid")
    with refuses("scope_denied"):
        create(setup, scopes=["*"])
    grant = create(setup, scopes=["publication.read"])
    for operation, data, error in (
        ("publication.publish", {"document": "ok"}, "scope_denied"),
        ("publication.read", {"document": "ok", "url": "other"}, "input_schema"),
        ("publication.read", {"document": 1}, "input_schema"),
        ("publication.read", {"document": "over" * 3000}, "budget_exceeded"),
        ("publication.read", {"document": "a\n"}, "input_schema"),
        ("absent", {}, "operation_unavailable"),
    ):
        with refuses(error):
            approved_call(runtime, session, grant, operation, data, approve_effect=lambda _: pytest.fail())
    with refuses("connection_unavailable"):
        approved_call(runtime, runtime.vault.sessions.create(), grant, "publication.read", {"document": "ok"})
    with refuses("provider_unavailable"):
        runtime.authorize(session, "absent", origin="", identity="", scopes=[], minutes=1, certificate="")
    assert backend.reads == [] and not fixtures["publication-test"].events


def test_expiry_revocation_while_consent_pending_and_renewal(setup):
    runtime, session, fixtures, backend, now = setup
    grant = create(setup)
    def expire(_):
        now[0] += timedelta(minutes=1)
        return True
    with refuses("connection_expired"):
        approved_call(runtime, session, grant, "publication.publish", {"document": "ok"}, approve_effect=expire)
    assert runtime.status(session, grant)["state"] == "expired"
    runtime.renew(session, grant, 5)
    assert runtime.status(session, grant)["state"] == "connected"
    def revoke(_):
        runtime.revoke(session, grant)
        return True
    with refuses("connection_revoked"):
        approved_call(runtime, session, grant, "publication.publish", {"document": "ok"}, approve_effect=revoke)
    runtime.revoke(session, grant)
    with refuses("connection_revoked"):
        runtime.renew(session, grant, 5)
    assert not backend.values and not backend.reads and not fixtures["publication-test"].events


def test_tls_identity_checked_before_secret_resolution(setup):
    runtime, session, fixtures, backend, _ = setup
    grant = create(setup, certificate=fixtures["catalogue-test"].certificate.read_text())
    with refuses("destination_denied"):
        approved_call(runtime, session, grant, "publication.read", {"document": "ok"})
    assert not backend.reads and not fixtures["publication-test"].events


def test_untrusted_responses_and_redirects(setup):
    runtime, session, fixtures, _, _ = setup
    grant = create(setup)
    publication = fixtures["publication-test"]
    for reply, code in (
        ((302, {}, fixtures["catalogue-test"].origin), "destination_denied"),
        ((200, {"published": True, "key": publication.token}), "output_schema"),
        ((200, {"published": "yes"}), "output_schema"),
        ((200, {"junk": "a" * 9000}), "budget_exceeded"),
    ):
        publication.override = reply
        with refuses(code) as exc:
            approved_call(runtime, session, grant, "publication.read", {"document": "ok"})
        assert publication.token not in str(exc.value)
    assert not fixtures["catalogue-test"].events
    assert len(publication.events) == 4


def test_provider_identity_and_key_checked_and_minimized(setup, tmp_path):
    runtime, session, fixtures, backend, _ = setup
    for overrides in ({"identity": "viewer"}, {"secret": bytearray(b"wrong")}):
        grant = create(setup, **overrides)
        with refuses("provider_denied"):
            approved_call(runtime, session, grant, "publication.read", {"document": "ok"})
        runtime.revoke(session, grant)
    assert not backend.values
    assert not fixtures["publication-test"].published("ok")
    for file in tmp_path.glob("*.sqlite"):
        assert b"synthetic-secret" not in file.read_bytes()
    assert "synthetic-secret" not in json.dumps(fixtures["publication-test"].events)

def test_network_consent_is_fresh_and_bound_to_payload(setup, monkeypatch):
    runtime, session, fixtures, backend, _ = setup
    grant = create(setup)
    data = {"document": "sample"}
    with refuses("egress_approval_required"):
        runtime.call(session, grant, "publication.read", data)
    with refuses("egress_approval_required"):
        runtime.call(session, grant, "publication.publish", data, approve_egress=lambda _: False,
                     approve_effect=lambda _: pytest.fail())
    clock = [10.]
    monkeypatch.setattr("akasha_brain.service_connections.monotonic", lambda: clock[0])
    def too_late(preview):
        assert preview["destination"] == fixtures["publication-test"].origin + "/v1/document?document=sample"
        assert preview["identity"] == "editor" and preview["authentication"] == "api_key"
        clock[0] += 300
        return True
    with refuses("approval_expired"):
        runtime.call(session, grant, "publication.read", data, approve_egress=too_late)
    assert backend.reads == [] and not fixtures["publication-test"].events


def test_another_session_cannot_inspect_renew_revoke_or_resolve(setup):
    runtime, session, fixtures, backend, _ = setup
    grant = create(setup)
    other = runtime.vault.sessions.create()
    fixture = fixtures["publication-test"]
    fixture.accounts["reader"] = "other-secret"
    own = runtime.authorize(other, fixture.name, origin=fixture.origin, identity="reader",
                            scopes=["publication.read"], minutes=2, certificate=fixture.certificate.read_text(),
                            secret=bytearray(b"other-secret"))
    for attempt in (lambda: runtime.status(other, grant), lambda: runtime.renew(other, grant, 5),
                    lambda: runtime.revoke(other, grant),
                    lambda: approved_call(runtime, other, grant, "publication.read", {"document": "demo"})):
        with refuses("connection_unavailable"):
            attempt()
    assert set(runtime.vault.handles(other)).isdisjoint(runtime.vault.handles(session))
    assert len(runtime.vault.handles(session)) == 1 and not backend.reads
    assert not fixtures["publication-test"].events
    for actor, connection, identity in ((session, grant, "editor"), (other, own, "reader")):
        output = approved_call(runtime, actor, connection, "publication.read", {"document": "sample"})
        assert output["provenance"]["identity"] == identity
        assert backend.reads[-1] == runtime.vault.handles(actor)[0]
    runtime.revoke(session, grant)
    assert approved_call(runtime, other, own, "publication.read", {"document": "sample"})["result"] == {"published": False}


def test_manifest_replacement_invalidates_old_grant_and_secret_echo_blocked(setup, tmp_path):
    runtime, session, fixtures, backend, _ = setup
    grant = create(setup)
    path = tmp_path / "registry.json"
    entries = json.loads(path.read_bytes())
    entries[1]["operations"][0]["output_schema"]["properties"]["published"] = {"type": "string"}
    path.write_text(json.dumps(entries))
    restarted = Connections(runtime.vault, registry_path=path)
    with refuses("connection_configuration_changed"):
        approved_call(restarted, session, grant, "publication.read", {"document": "sample"})
    with refuses("connection_configuration_changed"):
        restarted.renew(session, grant, 5)
    assert not backend.reads
    new_grant = create((restarted, session, fixtures, backend, None))
    fixtures["publication-test"].override = (200, {"published": "reflected: synthetic-secret"})
    with refuses("credential_in_response"):
        approved_call(restarted, session, new_grant, "publication.read", {"document": "sample"})


@pytest.mark.parametrize(("field", "value"), [
    ("origin", "http://localhost"), ("origin", "https://*.example.org"), ("origin", "https://a.example/p"),
    ("adapter", "arbitrary-python.v2"), ("version", ">=1"), ("path", "//other.example"),
    ("path", "/a/../b"), ("method", "DELETE"), ("effect", "persistent"),
    ("input_schema", {"$ref": "https://somewhere.invalid/schema"}),
])
def test_invalid_registry_is_refused_at_startup(tmp_path, field, value):
    entries = json.loads(DEFAULT_REGISTRY.read_bytes())
    entry = entries[0] if field in entries[0] else entries[0]["operations"][0]
    entry[field] = value
    path = tmp_path / "operator.json"
    path.write_text(json.dumps(entries))
    with refuses("registry_invalid"):
        load_registry(path)

def test_cli_default_matches_desktop_and_bench_can_override(tmp_path, monkeypatch):
    from akasha_brain.desktop_settings import app_directory
    from akasha_brain.service_cli import parser

    cli = parser()
    assert cli.parse_args(["list"]).directory == app_directory() / "runs"
    assert cli.parse_args(["--directory", str(tmp_path), "list"]).directory == tmp_path
    monkeypatch.setattr("akasha_brain.service_cli.app_directory", lambda: tmp_path)
    assert parser().parse_args(["list"]).registry == DEFAULT_REGISTRY
    installed = tmp_path / "service-adapters.json"
    installed.write_text("[]")
    assert parser().parse_args(["list"]).registry == installed
    with refuses("registry_invalid"):
        load_registry(installed)

@pytest.mark.parametrize("stage", ["dns", "tls", "credential"])
def test_committed_revocation_during_preparation_prevents_http_send(setup, tmp_path, monkeypatch, stage):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    import ssl
    from threading import Event
    from akasha_brain import service_connections

    runtime, session, fixtures, backend, _ = setup
    peer = Connections(runtime.vault, registry_path=tmp_path / "registry.json")
    grant = create(setup)
    reached, resume = Event(), Event()

    def pause():
        reached.set()
        assert resume.wait(3), "La révocation concurrente est restée bloquée pendant la préparation."

    if stage == "dns":
        resolve = service_connections.network_address
        def resolve_then_pause(*args):
            result = resolve(*args)
            pause()
            return result
        monkeypatch.setattr(service_connections, "network_address", resolve_then_pause)
    elif stage == "tls":
        wrap = ssl.SSLContext.wrap_socket
        def handshake_then_pause(context, *args, **kwargs):
            sock = wrap(context, *args, **kwargs)
            if not kwargs.get("server_side"):
                pause()
            return sock
        monkeypatch.setattr(ssl.SSLContext, "wrap_socket", handshake_then_pause)
    else:
        resolve_key = runtime.vault.resolve
        @contextmanager
        def unlock_then_pause(*args, **kwargs):
            with resolve_key(*args, **kwargs) as value:
                pause()
                yield value
        monkeypatch.setattr(runtime.vault, "resolve", unlock_then_pause)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(approved_call, runtime, session, grant, "publication.publish", {"document": "racing"},
                              approve_effect=lambda _: True)
        try:
            assert reached.wait(2)
            peer.revoke(session, grant)
            assert peer.status(session, grant)["state"] == "revoked"
        finally:
            resume.set()
        with refuses("connection_revoked"):
            pending.result(timeout=3)
    assert not fixtures["publication-test"].published("racing") and not fixtures["publication-test"].events
    assert len(backend.reads) == int(stage == "credential") and not backend.values
