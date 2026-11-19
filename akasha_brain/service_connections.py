"""Connexions personnelles aux services déclarés, accord d'effet et transport HTTPS."""

from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from hashlib import sha256
import http.client
from ipaddress import ip_address
import json
from queue import Empty, Queue
import re
import socket
import ssl
from threading import Thread, Timer
from time import monotonic
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator
from contracts.akasha_contracts.authz import authorize

from . import project_audit
from .conversation_vault import SessionVault
from .memory_store import MemoryRefusal, connect, stamp
from .service_registry import ADAPTER, DEFAULT_REGISTRY, MAX_BYTES, TIMEOUT_S, ServiceError, load_registry, unique_keys
from .vault_windows import KeyStoreUnavailable, SECRET_MAX_BYTES, SecretMissing


def interval(minutes):
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise ServiceError("ttl_invalid")
    return timedelta(minutes=minutes)


def peer_certificate(pem):
    try:
        der = ssl.PEM_cert_to_DER_cert(pem.strip())
        canonical = ssl.DER_cert_to_PEM_cert(der)
        if canonical.strip() != pem.strip().replace("\r\n", "\n"):
            raise ValueError()
        tls_context(canonical)
    except (TypeError, ValueError, ssl.SSLError):
        raise ServiceError("certificate_invalid") from None
    return canonical


def tls_context(pem):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=pem)
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context


def encoded(data):
    try:
        return json.dumps(data, ensure_ascii=True, allow_nan=False, sort_keys=True).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        raise ServiceError("input_schema") from None


def expire_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def network_address(host, port, timeout):
    try:
        return str(ip_address(host))
    except ValueError:
        pass
    answer = Queue(maxsize=1)

    def resolve():
        try:
            answer.put([ip_address(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)])
        except (OSError, ValueError):
            answer.put([])

    Thread(target=resolve, daemon=True).start()
    try:
        addresses = answer.get(timeout=timeout)
    except Empty:
        raise ServiceError("budget_exceeded") from None
    if not addresses:
        raise ServiceError("provider_unavailable")
    if any(not addr.is_global or addr.is_multicast for addr in addresses):
        raise ServiceError("destination_denied")
    return str(addresses[0])


def response_data(conn, op, secret):
    with conn.getresponse() as response:
        if 300 <= response.status < 400:
            raise ServiceError("destination_denied")
        if response.status in (401, 403):
            raise ServiceError("provider_denied")
        if response.status != 200:
            raise ServiceError("provider_failed")
        if response.headers.get_content_type() != "application/json":
            raise ServiceError("output_schema")
        expected = response.length
        if expected is not None and expected > MAX_BYTES:
            raise ServiceError("budget_exceeded")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ServiceError("budget_exceeded")
        if expected is not None and len(raw) != expected:
            raise ServiceError("provider_failed")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_keys)
        json.dumps(result, allow_nan=False)
    except (ValueError, RecursionError):
        raise ServiceError("output_schema") from None
    if not Draft202012Validator(op.outputs).is_valid(result):
        raise ServiceError("output_schema")
    if secret is not None and any(secret in str(value).encode("utf-8", "surrogatepass")
                                  for value in (*result, *result.values())):
        raise ServiceError("credential_in_response")
    return result


def resource_path(op, data):
    if not op.writes and data:
        return op.path + "?" + urlencode(data)
    return op.path


def request(service, op, row, data, credential, check_live, sending):
    origin = urlsplit(service.origin)
    endpoint = service.origin + op.path
    manifest = op.manifest(service)
    permissions = manifest["permissions"]
    if (row["origin"] != service.origin or endpoint not in permissions["network"]
            or (op.writes and endpoint not in permissions["writes"])
            or not set(data) <= set(permissions["reads"])):
        raise ServiceError("destination_denied")
    path = resource_path(op, data)
    body = None
    headers = {"Accept": "application/json", "Connection": "close"}
    if op.writes:
        body = encoded(data)
        headers["Content-Type"] = "application/json"
    start = monotonic()
    context = tls_context(row["certificate"])
    port = origin.port or 443
    conn = http.client.HTTPSConnection(origin.hostname, port, context=context, timeout=TIMEOUT_S)
    conn.auto_open = False
    try:
        address = network_address(origin.hostname, port, TIMEOUT_S)
        check_live()
        remaining = TIMEOUT_S - (monotonic() - start)
        if remaining <= 0:
            raise ServiceError("budget_exceeded")
        with socket.create_connection((address, port), timeout=remaining) as tcp:
            remaining = TIMEOUT_S - (monotonic() - start)
            if remaining <= 0:
                raise ServiceError("budget_exceeded")
            tcp.settimeout(remaining)
            conn.sock = context.wrap_socket(tcp, server_hostname=origin.hostname)
        sock = conn.sock
        peer = sock.getpeercert(binary_form=True)
        if peer != ssl.PEM_cert_to_DER_cert(row["certificate"]):
            raise ServiceError("destination_denied")
        check_live()
        timer = Timer(max(0, TIMEOUT_S - (monotonic() - start)), expire_socket, args=(sock,))
        timer.daemon = True
        timer.start()
        try:
            with credential as secret:
                if secret is not None:
                    headers["Authorization"] = b"Bearer " + bytes(secret)
                    headers["X-Akasha-Identity"] = row["identity"]
                try:
                    with sending():
                        if monotonic() - start >= TIMEOUT_S:
                            raise ServiceError("budget_exceeded")
                        conn.request(op.method, path, body=body, headers=headers)
                finally:
                    headers.pop("Authorization", None)
                result = response_data(conn, op, secret)
            if monotonic() - start >= TIMEOUT_S:
                raise ServiceError("budget_exceeded")
        finally:
            timer.cancel()
    except ssl.SSLCertVerificationError:
        raise ServiceError("destination_denied") from None
    except (OSError, http.client.HTTPException):
        code = "budget_exceeded" if monotonic() - start >= TIMEOUT_S else "provider_unavailable"
        raise ServiceError(code) from None
    finally:
        conn.close()
    return result, service.origin + path, sha256(peer).hexdigest()


class Connections:
    def __init__(self, vault: SessionVault, *, registry_path=DEFAULT_REGISTRY):
        self.services = load_registry(registry_path)
        self.vault = vault
        self.clock = vault.sessions.clock
        self.path = vault.path.with_name("service-connections.sqlite")
        if self.path.resolve() != self.path:
            raise ServiceError("storage_invalid")
        with connect(self.path, create=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS grants (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, service TEXT NOT NULL, origin TEXT NOT NULL,
                identity TEXT NOT NULL, scopes TEXT NOT NULL, expires TEXT NOT NULL, revoked INTEGER NOT NULL,
                certificate TEXT NOT NULL, handle TEXT, adapter TEXT NOT NULL)""")

    def authorize(self, session, name, *, origin, identity, scopes, minutes, certificate, secret=None):
        service = self.provider(name)
        if origin != service.origin:
            raise ServiceError("destination_denied")
        scopes = sorted(set(scopes))
        if not scopes or not set(scopes) <= {op.id for op in service.operations}:
            raise ServiceError("scope_denied")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", identity) or (not service.authenticated and identity != "public"):
            raise ServiceError("identity_invalid")
        if service.authenticated != (secret is not None):
            raise ServiceError("credential_required")
        if secret is not None and (type(secret) is not bytearray or len(secret) > SECRET_MAX_BYTES
                                   or not re.fullmatch(rb"[!-~]+", secret)):
            raise ServiceError("credential_invalid")
        certificate = peer_certificate(certificate)
        expires = stamp(self.clock() + interval(minutes))
        self.vault.require_session(session)
        handle = self.vault.seal(session, secret) if service.authenticated else None
        grant = str(uuid4())
        try:
            with connect(self.path) as db:
                db.execute("INSERT INTO grants VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                           (grant, str(session), name, origin, identity, json.dumps(scopes), expires,
                            certificate, str(handle) if handle else None, service.fingerprint))
                project_audit.record(self.path, action="services.connect", risk="R3", actor="operator",
                                     decision="approved")
        except Exception:
            if handle:
                self.vault.erase(session, handle)
            raise
        return grant

    def provider(self, name):
        if name not in self.services:
            raise ServiceError("provider_unavailable")
        return self.services[name]

    def row(self, db, session, grant):
        self.vault.require_session(session)
        row = db.execute("SELECT * FROM grants WHERE session = ? AND id = ?", (str(session), grant)).fetchone()
        if row is None:
            raise ServiceError("connection_unavailable")
        return row

    def state(self, row):
        if row["revoked"]:
            return "revoked"
        if self.clock() >= datetime.fromisoformat(row["expires"]):
            return "expired"
        service = self.services.get(row["service"])
        if service is None or service.fingerprint != row["adapter"]:
            return "configuration_changed"
        return "connected"

    def status(self, session, grant):
        with connect(self.path) as db:
            row = self.row(db, session, grant)
            return {"connection": grant, "service": row["service"], "identity": row["identity"],
                    "destination": row["origin"], "scopes": json.loads(row["scopes"]),
                    "expires_at": row["expires"], "state": self.state(row)}

    def renew(self, session, grant, minutes):
        duration = interval(minutes)
        with connect(self.path) as db:
            row = self.row(db, session, grant)
            if row["revoked"]:
                raise ServiceError("connection_revoked")
            if row["adapter"] != self.provider(row["service"]).fingerprint:
                raise ServiceError("connection_configuration_changed")
            if row["handle"] and UUID(row["handle"]) not in self.vault.handles(session):
                raise ServiceError("credential_unavailable")
            db.execute("UPDATE grants SET expires = ? WHERE id = ?", (stamp(self.clock() + duration), grant))

    def revoke(self, session, grant):
        with connect(self.path) as db:
            self.row(db, session, grant)
            db.execute("UPDATE grants SET revoked = 1 WHERE id = ?", (grant,))
        # La révocation est durable même si le coffre doit être nettoyé à la prochaine tentative.
        with connect(self.path) as db:
            row = self.row(db, session, grant)
            if row["handle"]:
                handle = UUID(row["handle"])
                if handle in self.vault.handles(session):
                    self.vault.erase(session, handle)
                db.execute("UPDATE grants SET handle = NULL WHERE id = ?", (grant,))

    def admitted(self, db, session, grant, operation):
        row = self.row(db, session, grant)
        state = self.state(row)
        if state != "connected":
            raise ServiceError("connection_" + state)
        service = self.provider(row["service"])
        op = service.operation(operation)
        if op.id not in json.loads(row["scopes"]):
            raise ServiceError("scope_denied")
        if service.origin != row["origin"]:
            raise ServiceError("destination_denied")
        if service.authenticated != bool(row["handle"]):
            raise ServiceError("credential_unavailable")
        return row, service, op

    def call(self, session, grant, operation, data, *, approve_egress=None, approve_effect=None):
        try:
            return self._call(session, grant, operation, data, approve_egress, approve_effect)
        except ServiceError as exc:
            project_audit.record(self.path, action="services.call", risk="R3", actor="operator",
                                 decision="failed", reason=exc.code)
            raise

    def _call(self, session, grant, operation, data, approve_egress, approve_effect):
        payload = encoded(data)
        if len(payload) > MAX_BYTES:
            raise ServiceError("budget_exceeded")
        data = json.loads(payload)
        with connect(self.path) as db:
            row, service, op = self.admitted(db, session, grant, operation)
            if not Draft202012Validator(op.inputs).is_valid(data):
                raise ServiceError("input_schema")
        destination = service.origin + resource_path(op, data)
        if len(destination) > MAX_BYTES:
            raise ServiceError("budget_exceeded")
        preview = {"connection": grant, "identity": row["identity"], "service": service.id,
                   "operation": op.id, "destination": destination, "effect": op.effect,
                   "purpose": op.purpose, "method": op.method, "authentication": "api_key" if service.authenticated else "none",
                   "expires_at": row["expires"], "input": json.loads(payload)}
        review_until = monotonic() + 300
        approved = approve_egress is not None and approve_egress(dict(preview, input=json.loads(payload))) is True
        if authorize({"risk_class": "R3", "human_approval": approved}):
            raise ServiceError("egress_approval_required")
        if op.writes:
            if approve_effect is None or approve_effect(preview) is not True:
                raise ServiceError("effect_approval_required")

        def revalidate(db):
            self.admitted(db, session, grant, operation)
            if monotonic() >= review_until:
                raise ServiceError("approval_expired")

        def check_live():
            with connect(self.path) as db:
                revalidate(db)
            return True

        @contextmanager
        def sending():
            # La révocation et l’envoi HTTP prennent le même verrou, après TLS et après la lecture du coffre.
            with connect(self.path) as db:
                revalidate(db)
                yield

        check_live()
        project_audit.record(self.path, action=op.id, risk="R3", actor="operator", decision="approved")
        credential = nullcontext(None)
        if service.authenticated:
            credential = self.vault.resolve(session, UUID(row["handle"]), approve=check_live)
        try:
            result, url, certificate_hash = request(service, op, row, data, credential, check_live, sending)
        except (SecretMissing, KeyStoreUnavailable, MemoryRefusal):
            check_live()
            raise ServiceError("credential_unavailable") from None
        return {"result": result, "provenance": {"service": service.id, "operation": op.id,
                "version": service.version, "adapter": ADAPTER, "identity": row["identity"], "destination": url,
                "peer_sha256": certificate_hash, "observed_at": stamp(self.clock()), "source": "external"}}
