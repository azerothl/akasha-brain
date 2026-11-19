"""Lecture HTTPS publique et accord ponctuel, sur l’hôte Akasha."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
import ipaddress
import json
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import subprocess
import sys
from threading import Lock
from time import monotonic
from urllib.parse import quote, urlsplit
from uuid import uuid4

from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .experience import transaction
from .planning import PlanningError

URL_PATTERN = re.compile(r"""(?i:\bhttps?)://[^\s<>"«»`]+""")
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
GLOBAL_IPV6 = ipaddress.IPv6Network("2000::/3")
MAX_URL = 2048
MAX_BYTES = 256 * 1024
MAX_TEXT = 8000
TIMEOUT = 15
APPROVAL_SECONDS = 300


def clean_reference(raw: str) -> str:
    bare = raw.rstrip(".,;!?")
    cleaned = bare
    opening = {")": "(", "]": "[", "}": "{"}
    while cleaned and cleaned[-1] in opening:
        closing = cleaned[-1]
        if cleaned.count(closing) <= cleaned.count(opening[closing]):
            break
        cleaned = cleaned[:-1]
    # Une ponctuation dans la valeur d’un paramètre peut faire partie de l’URL.
    return cleaned if cleaned != bare or "?" not in bare.partition("#")[0] else raw


@dataclass(frozen=True)
class Target:
    host: str
    resource: str

    @property
    def url(self) -> str:
        return f"https://{self.host}{self.resource}"


def reject(code: ErrorCode, message: str):
    raise PlanningError(AkashaError(code, message))


def public_target(url: str) -> Target:
    try:
        if len(url) > MAX_URL or "\\" in url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
            raise ValueError
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in (None, 443) or parts.username is not None:
            raise ValueError
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().removesuffix(".")
        labels = host.split(".")
        if len(labels) < 2 or len(host) > 253 or labels[-1].isdigit() or not all(map(LABEL.fullmatch, labels)):
            raise ValueError
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="/?%:@!$&'()*+,;=-._~")
        target = Target(host, path + ("?" + query if query else ""))
        if len(target.url) > MAX_URL:
            raise ValueError
    except ValueError:
        reject(ErrorCode.PERMISSION_DENIED, "Indiquez une URL HTTPS publique sur le port standard, sans identifiants.")
    return target


@dataclass(frozen=True)
class Observation:
    url: str
    collected_at: str
    text: str
    truncated: bool


@dataclass(frozen=True)
class ReadReview:
    target: Target
    request_id: str = field(default_factory=lambda: str(uuid4()))
    expires_at: float = field(default_factory=lambda: monotonic() + APPROVAL_SECONDS)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)
    _used: bool = field(default=False, init=False, repr=False, compare=False)

    def collect(self, audit_path: Path, *, approved: bool, cancelled) -> Observation:
        with self._lock:
            try:
                if error := authorize({"risk_class": "R3", "human_approval": approved}):
                    raise PlanningError(error)
                if self._used:
                    reject(ErrorCode.GRANT_BUDGET_EXHAUSTED, "Cet accord de lecture a déjà été utilisé.")
                if monotonic() >= self.expires_at:
                    reject(ErrorCode.APPROVAL_EXPIRED, "L’accord de lecture a expiré. Redemandez l’ouverture du lien.")
                if cancelled():
                    reject(ErrorCode.PERMISSION_DENIED, "Lecture annulée.")
            except PlanningError as error:
                self._audit(audit_path, error.error.code.value)
                raise
            object.__setattr__(self, "_used", True)
            self._audit(audit_path, "authorized")
        try:
            if cancelled():
                reject(ErrorCode.PERMISSION_DENIED, "Lecture annulée.")
            observation = bounded_read(self.target)
        except PlanningError as error:
            self._audit(audit_path, error.error.code.value)
            raise
        self._audit(audit_path, "collected")
        return observation

    def _audit(self, path: Path, outcome: str):
        try:
            with transaction(path) as db:
                db.execute("""CREATE TABLE IF NOT EXISTS web_audit (
                    seq INTEGER PRIMARY KEY, request_id TEXT NOT NULL, created_at TEXT NOT NULL, outcome TEXT NOT NULL
                )""")
                db.execute("INSERT INTO web_audit (request_id, created_at, outcome) VALUES (?, ?, ?)",
                           (self.request_id, datetime.now(timezone.utc).isoformat(), outcome))
        except (OSError, sqlite3.Error):
            reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Le journal des autorisations réseau est indisponible.")


def bounded_read(target: Target) -> Observation:
    try:
        completed = subprocess.run(
            [sys.executable, "-E", "-B", "-m", "akasha_brain.web_collection"],
            cwd=Path(__file__).resolve().parents[1],
            input=target.url.encode("utf-8"), capture_output=True, timeout=TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode:
            raise ValueError
        payload = json.loads(completed.stdout)
        if "error" in payload:
            code, message = payload["error"]
            reject(ErrorCode(code), message)
        return Observation(target.url, payload["collected_at"], payload["text"], payload["truncated"])
    except subprocess.TimeoutExpired:
        reject(ErrorCode.TIMEOUT_EXCEEDED, "La lecture de la page a dépassé le délai autorisé.")
    except (OSError, ValueError, KeyError):
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "La lecture HTTPS n’a pas abouti.")


def public_address(host: str) -> str:
    answers = socket.getaddrinfo(host + ".", 443, type=socket.SOCK_STREAM)
    addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
    for address in addresses:
        if (not address.is_global or address.is_multicast or
                isinstance(address, ipaddress.IPv6Address) and (
                    address not in GLOBAL_IPV6 or address.sixtofour or address.teredo or address.scope_id)):
            reject(ErrorCode.PERMISSION_DENIED, "Le domaine résout vers une adresse réseau non autorisée.")
    if not addresses:
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Le domaine n’a fourni aucune adresse utilisable.")
    return str(next((address for address in addresses if address.version == 4), addresses[0]))


class PublicConnection(HTTPConnection):
    default_port = 443

    def connect(self):
        address = public_address(self.host)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_default_certs()
        tcp = socket.create_connection((address, 443), self.timeout)
        try:
            # La connexion utilise l’adresse contrôlée et TLS vérifie le nom approuvé.
            self.sock = context.wrap_socket(tcp, server_hostname=self.host)
        except (OSError, ValueError):
            tcp.close()
            raise


class VisibleText(HTMLParser):
    ignored = {"script", "style", "template", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if self.hidden and self.hidden[-1] == tag:
            self.hidden.pop()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def read_public_text(target: Target) -> dict:
    connection = PublicConnection(target.host, port=443, timeout=5)
    try:
        connection.request("GET", target.resource, headers={
            "User-Agent": "AkashaBrain/1.0",
            "Accept": "text/html, text/plain, text/markdown, application/json",
            "Accept-Encoding": "identity",
        })
        with connection.getresponse() as response:
            if 300 <= response.status < 400:
                reject(ErrorCode.PERMISSION_DENIED, "La page redirige. Indiquez son adresse HTTPS finale.")
            if response.status != 200:
                reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, f"Le site a répondu HTTP {response.status}.")
            # Le parseur MIME suppose text/plain lorsqu’aucun type n’est déclaré.
            kind = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
            if (kind not in {"text/html", "text/plain", "text/markdown", "application/json"} or
                    response.headers.get("Content-Encoding", "identity").lower() != "identity"):
                reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Le format de la réponse n’est pas pris en charge.")
            data = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    finally:
        connection.close()
    try:
        text = data[:MAX_BYTES].decode(charset, errors="replace")
    except (LookupError, ValueError, TypeError):
        text = data[:MAX_BYTES].decode("utf-8", errors="replace")
    if kind == "text/html":
        parser = VisibleText()
        parser.feed(text)
        parser.close()
        text = " ".join(parser.parts)
    text = "".join(char if char.isprintable() or char.isspace() else " " for char in text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not text:
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "La page ne fournit aucun texte lisible.")
    return {"collected_at": datetime.now(timezone.utc).isoformat(), "text": text[:MAX_TEXT],
            "truncated": len(data) > MAX_BYTES or len(text) > MAX_TEXT}


def main():
    try:
        result = read_public_text(public_target(sys.stdin.buffer.read(MAX_URL + 1).decode("utf-8")))
    except PlanningError as error:
        result = {"error": [error.error.code.value, error.error.message]}
    except TimeoutError:
        result = {"error": [ErrorCode.TIMEOUT_EXCEEDED.value, "Le site n’a pas répondu dans le délai autorisé."]}
    except socket.gaierror:
        result = {"error": [ErrorCode.ENVIRONMENT_OBSERVATION_FAILED.value, "Le domaine n’a pas pu être résolu."]}
    except (OSError, HTTPException, ValueError):
        result = {"error": [ErrorCode.ENVIRONMENT_OBSERVATION_FAILED.value, "La lecture HTTPS n’a pas abouti."]}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
