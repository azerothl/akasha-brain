"""Rejouer G11 sur Windows avec deux pairs TLS, une clé éphémère et la CLI en processus séparés."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from secrets import token_urlsafe
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
from uuid import UUID

from akasha_brain.conversation_sessions import SessionStore
from akasha_brain.conversation_vault import SessionVault
from akasha_brain.project_audit import verify
from akasha_brain.service_connections import Connections
from akasha_brain.service_registry import DEFAULT_REGISTRY, ServiceError
from akasha_brain.vault_windows import SecretMissing, WindowsKeyStore
from bench.service_test_providers import providers, running_provider


def revoke_before_send(vault, session, grant, fixture, revoke):
    resolved, resume = Event(), Event()

    class PausedVault(SessionVault):
        @contextmanager
        def resolve(self, *args, **kwargs):
            with super().resolve(*args, **kwargs) as secret:
                resolved.set()
                if not resume.wait(10):
                    raise AssertionError("La révocation est restée bloquée avant l’envoi.")
                yield secret

    runtime = Connections(PausedVault(vault.path.parent, vault.sessions))
    before = len(fixture.events)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(runtime.call, session, grant, "publication.publish", {"document": "course"},
                                approve_egress=lambda _: True, approve_effect=lambda _: True)
        try:
            assert resolved.wait(5)
            assert revoke()["state"] == "revoked"
        finally:
            resume.set()
        try:
            pending.result(timeout=5)
        except ServiceError as exc:
            assert exc.code == "connection_revoked"
        else:
            raise AssertionError("Publication acceptée après révocation.")
    delta = len(fixture.events) - before
    assert delta == 0 and not fixture.published("course")
    return {"stage": "after_tls_and_windows_credential_read", "other_process": "service_cli revoke",
            "outcome": "connection_revoked", "http_requests_received": delta, "published": False}


def run(root):
    token = token_urlsafe(32)
    directory = root / "client"
    prefix = [sys.executable, "-B", "-X", "utf8", "-m", "akasha_brain.service_cli", "--directory", str(directory)]
    registry_path = DEFAULT_REGISTRY
    transcript = []
    markers = (token.encode(), token.encode("utf-16le"), sha256(token.encode()).hexdigest().encode(),
               sha256(token.encode()).digest())

    def clean(data):
        assert all(marker not in data for marker in markers), "Le témoin a quitté le périmètre autorisé."

    def inspect_files():
        for file in root.rglob("*"):
            if file.is_file():
                clean(file.read_bytes())

    def cli(*args, stdin="", error=None):
        result = subprocess.run([*prefix, "--registry", str(registry_path), *map(str, args)],
                                input=stdin, capture_output=True, encoding="utf-8",
                                timeout=25)
        clean((result.stdout + result.stderr).encode())
        assert result.returncode == int(error is not None), (args[0], result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        if error:
            assert payload == {"error": error}, (payload, error)
        transcript.append({"command": args[0], "outcome": error or "ok"})
        return payload

    listing = cli("list")
    assert {entry["service"] for entry in listing} == {"catalogue-test", "publication-test"}
    sid = cli("session")["session"]
    session = UUID(sid)
    session_args = ["--session", sid]
    vault = SessionVault(directory, SessionStore(directory / "conversation-sessions.sqlite"))
    with providers(root, token, fixed_ports=True) as fixtures:
        public, private = fixtures["catalogue-test"], fixtures["publication-test"]
        def grant(provider, *scopes, destination=None, error=None):
            options = ["--scope", scopes[0]]
            for scope in scopes[1:]:
                options.extend(["--scope", scope])
            if provider.token:
                options.append("--key-stdin")
            return cli("connect", provider.name, *session_args, "--certificate", provider.certificate,
                       "--destination", destination or provider.origin, "--identity", "editor" if provider.token else "public",
                       "--minutes", 1, *options, stdin=token + "\n" if provider.token else "", error=error)

        def call(connection, operation, data, *, answer="", network="ENVOYER", error=None):
            return cli("call", operation, *session_args, "--connection", connection, "--input", json.dumps(data),
                       stdin=network + "\n" + answer, error=error)

        try:
            grant(public, "catalogue.status", destination=private.origin, error="destination_denied")
            g0 = grant(public, "catalogue.status")
            read = grant(private, "publication.read")
            both = grant(private, "publication.read", "publication.publish")
            data = {"document": "bulletin"}
            read_args = [*session_args, "--connection", read["connection"]]
            both_args = [*session_args, "--connection", both["connection"]]
            assert len(vault.handles(session)) == 2
            inspect_files()
            handles = vault.handles(session)
            other = cli("session")["session"]
            for action in ("status", "revoke"):
                cli(action, "--session", other, "--connection", read["connection"], error="connection_unavailable")
            cli("call", "publication.read", "--session", other, "--connection", read["connection"], "--input",
                json.dumps(data), stdin="ENVOYER\n", error="connection_unavailable")
            assert not vault.handles(UUID(other)) and vault.handles(session) == handles
            assert not private.events and not public.events
            call(read["connection"], "publication.read", data, network="non", error="egress_approval_required")
            assert not private.events
            p0 = call(g0["connection"], "catalogue.status", {})
            p1 = call(read["connection"], "publication.read", data)
            assert p0["result"] == {"available": True} and p1["result"] == {"published": False}

            call(read["connection"], "publication.publish", data, answer="PUBLIER\n", error="scope_denied")
            call(both["connection"], "publication.publish", {"document": "a", "extra": "x"}, error="input_schema")
            call(both["connection"], "publication.publish", data, answer="non\n", error="effect_approval_required")
            assert len(private.events) == 1 and not private.published("bulletin")
            p2 = call(both["connection"], "publication.publish", data, answer="PUBLIER\n")
            p3 = call(read["connection"], "publication.read", data)
            assert p2["result"] == p3["result"] == {"published": True} and private.published("bulletin")
            assert [event["method"] for event in private.events] == ["GET", "PUT", "GET"]
            observed = [p0, p1, p2, p3]
            for record, fixture in zip(observed, (public, private, private, private), strict=True):
                source = record["provenance"]
                assert source["service"] == fixture.name and source["destination"].startswith(fixture.origin + "/")
                assert source["adapter"] == "service-https-json.v1" and source["source"] == "external"
                assert datetime.fromisoformat(source["observed_at"]).tzinfo
                der = ssl.PEM_cert_to_DER_cert(fixture.certificate.read_text())
                assert source["peer_sha256"] == sha256(der).hexdigest()

            private.override = (200, {"published": True, "untrusted": token})
            call(read["connection"], "publication.read", data, error="output_schema")
            private.override = (302, {}, public.origin)
            call(read["connection"], "publication.read", data, error="destination_denied")
            assert len(public.events) == 1
            private.override = None
            # Place l'horloge au bord exact de la permission sans raccourcir le TTL en production.
            end = datetime.fromisoformat(read["expires_at"])
            later = SessionStore(vault.sessions.path, clock=lambda: end)
            expired = Connections(SessionVault(directory, later))
            assert expired.status(session, read["connection"])["state"] == "expired"
            try:
                expired.call(session, read["connection"], "publication.read", data)
            except ServiceError as exc:
                assert exc.code == "connection_expired"
            else:
                raise AssertionError("La permission expirée a accepté un appel.")
            renewed = cli("renew", *read_args, "--minutes", 10)
            assert renewed["scopes"] == ["publication.read"] and datetime.fromisoformat(renewed["expires_at"]) > end
            race = revoke_before_send(vault, session, both["connection"], private, lambda: cli("revoke", *both_args))
            call(both["connection"], "publication.publish", data, answer="PUBLIER\n", error="connection_revoked")
            assert cli("disconnect", *read_args)["state"] == "revoked"
            assert not vault.handles(session)
            for handle in handles:
                try:
                    WindowsKeyStore().get(handle)
                except SecretMissing:
                    continue
                raise AssertionError("Clé toujours présente après déconnexion.")
            assert len(private.events) == 5 and all(evt["has_authorization"] for evt in private.events)
            assert not public.events[0]["has_authorization"]
            with running_provider("operator-status", root) as third:
                third.override = (200, {"available": True})
                entries = json.loads(DEFAULT_REGISTRY.read_bytes())
                imported = json.loads(json.dumps(entries[0]))
                imported.update(id=third.name, version="1.2.0", origin=third.origin)
                imported["operations"][0].update(id="operator.health", path="/custom/health")
                registry_path = root / "operator-registry.json"
                registry_path.write_text(json.dumps([*entries, imported]), encoding="utf-8")
                assert len(cli("list")) == 3
                extra = grant(third, "operator.health")
                result = call(extra["connection"], "operator.health", {})
                assert result["result"] == {"available": True}
                assert result["provenance"]["destination"] == third.origin + "/custom/health"
                assert result["provenance"]["version"] == "1.2.0" and len(third.events) == 1
                observed.append(result)
                cli("disconnect", *session_args, "--connection", extra["connection"])
            inspect_files()
            audit = verify(directory / "akasha-audit.sqlite")
            assert audit["status"] == "passed"
            return ({"status": "passed", "platform": sys.platform, "keystore": "Windows Credential Manager",
                     "commands": transcript, "expiry_check": {"clock": "injected at expires_at", "state": "expired",
                     "outcome": "connection_expired"}, "vault_entries_removed": len(handles),
                     "cross_session_access_denied": True, "operator_registry_loaded_in_new_process": True,
                     "concurrent_revocation": race,
                     "witness_absent_from_cli_and_files": True, "audit": audit, "observations": observed},
                    {"status": "passed", "events": {name: fixture.events for name, fixture in (fixtures | {third.name: third}).items()},
                     "published_before_approval": False, "published_after_approval": private.published("bulletin")})
        finally:
            for handle in vault.handles(session):
                vault.erase(session, handle)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", type=Path, required=True)
    args = cli.parse_args()
    if not __debug__:
        cli.error("Les assertions du rejeu doivent être actives.")
    with TemporaryDirectory(prefix="akasha-services-g11-") as temp:
        reports = run(Path(temp))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, report in zip(("service-connections-g11.json", "service-providers-g11.json"), reports, strict=True):
        path = args.output_dir / filename
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
