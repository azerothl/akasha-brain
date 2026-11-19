"""Deux fournisseurs HTTPS de qualification sur loopback. Chaque démarrage crée ses certificats."""

from contextlib import closing, ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import json
from pathlib import Path
import sqlite3
import ssl
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from akasha_brain.service_registry import load_registry


def tls_identity(name, root):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    public = root / (name + ".pem")
    public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with TemporaryDirectory() as temp:
        private = Path(temp) / "server.key"
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        context.load_cert_chain(public, private)
    return public, context


class Provider:
    def __init__(self, name, root, token, port):
        self.name = name
        self.token = token if name == "publication-test" else None
        self.accounts = {"editor": token} if self.token else {}
        self.events = []
        self.override = None
        self.database = root / "publication.sqlite"
        self.certificate, context = tls_identity(name, root)
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.provider = self
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.origin = f"https://127.0.0.1:{self.server.server_port}"
        if self.token:
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS publications(document TEXT PRIMARY KEY)")

    def published(self, document):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute("SELECT 1 FROM publications WHERE document = ?", (document,)).fetchone() is not None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value, redirect=None):
        payload = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if redirect:
            self.send_header("Location", redirect)
        self.end_headers()
        self.wfile.write(payload)

    def handle_operation(self):
        service = self.server.provider
        auth = self.headers.get("Authorization", "")
        identity = self.headers.get("X-Akasha-Identity")
        url = urlsplit(self.path)
        service.events.append({"method": self.command, "path": url.path, "has_authorization": bool(auth)})
        if service.token:
            expected = service.accounts.get(identity)
            if expected is None or not compare_digest(auth, "Bearer " + expected):
                return self.reply(403, {})
        if service.override is not None:
            return self.reply(*service.override)
        if service.name == "catalogue-test" and self.command == "GET" and self.path == "/v1/status":
            return self.reply(200, {"available": True})
        if service.name == "publication-test" and url.path == "/v1/document":
            if self.command == "PUT":
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 8192:
                    return self.reply(400, {})
                document = json.loads(self.rfile.read(size))["document"]
                with closing(sqlite3.connect(service.database)) as db, db:
                    db.execute("INSERT OR IGNORE INTO publications VALUES (?)", (document,))
            else:
                document = parse_qs(url.query)["document"][0]
            return self.reply(200, {"published": service.published(document)})
        self.reply(404, {})

    do_GET = do_PUT = handle_operation


@contextmanager
def running_provider(name, root, token=None, port=0):
    fixture = Provider(name, root, token, port)
    with fixture.server:
        thread = Thread(target=fixture.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield fixture
        finally:
            fixture.server.shutdown()
            thread.join()


@contextmanager
def providers(root, token, *, fixed_ports=False):
    services = {}
    with ExitStack() as stack:
        for name, service in load_registry().items():
            port = urlsplit(service.origin).port if fixed_ports else 0
            services[name] = stack.enter_context(running_provider(name, root, token, port))
        yield services


if __name__ == "__main__":
    from getpass import getpass
    from threading import Event

    with TemporaryDirectory(prefix="akasha-g11-") as temp:
        token = getpass("Clé API synthétique du compte editor : ")
        if not token or not token.isascii() or not token.isprintable() or " " in token:
            raise SystemExit("Choisissez une clé de test ASCII sans espace.")
        with providers(Path(temp), token, fixed_ports=True) as services:
            for service in services.values():
                print(service.name, service.origin, service.certificate, flush=True)
            try:
                Event().wait()
            except KeyboardInterrupt:
                pass
