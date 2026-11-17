"""Admission et résolution locale des secrets liés à une session."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import re
from uuid import UUID, uuid4

from . import project_audit
from .conversation_sessions import SessionId, SessionStore
from .memory_store import MemoryRefusal, connect, stamp
from .retention import deadline, load_policy
from .vault_windows import KeyStoreUnavailable, SECRET_MAX_BYTES, SecretMissing, WindowsKeyStore

LABELED = re.compile(r"(?:cl[ée]\s+api|api[ _-]?key|jeton\s+d['’]acc[èe]s|access[ _-]?token|secret)\s*[:=]",
                     re.IGNORECASE)
TOKEN = re.compile(r"(?:gh[pousr]_|github_pat_|sk-(?:proj-|live-)?)[A-Za-z0-9_-]{16,}")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def admit_secret(request: str) -> bytearray | None:
    """Reconnaît une clé seule ou explicitement étiquetée et refuse les demandes mixtes."""
    label = LABELED.search(request)
    value = request[label.end():].strip() if label and not label.start() else request
    if label or TOKEN.search(request) or PRIVATE_KEY.search(request):
        if ((label and label.start()) or (not label and not TOKEN.fullmatch(value))
                or not re.fullmatch(r"[!-~]+", value)):
            raise ValueError("Saisissez une seule clé API, précédée de « Clé API : » si nécessaire.")
        if len(value) > SECRET_MAX_BYTES:
            raise ValueError("La clé dépasse la limite du coffre Windows.")
        return bytearray(value, "ascii")
    return None


def clear(value: bytearray) -> None:
    value[:] = bytes(len(value))


class SessionVault:
    def __init__(self, directory: Path, sessions: SessionStore, *, keystore=WindowsKeyStore):
        nominal = directory.resolve() / "conversation-vault.sqlite"
        if nominal.resolve() != nominal:
            raise ValueError("Le fichier du coffre doit être local et sans lien.")
        self.path = nominal
        self.sessions = sessions
        self.keystore = keystore
        with connect(self.path, create=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS session_secrets (
                handle TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('sealing', 'live', 'erasing'))
            )""")

    def audit(self, action: str, decision: str) -> None:
        project_audit.record(self.path, action=action, risk="R2", actor="operator", decision=decision)

    def require_session(self, session_id: SessionId) -> str:
        key = self.sessions.key(session_id)
        with connect(self.sessions.path) as db:
            self.sessions.require(db, key)
        return key

    def seal(self, session_id: SessionId, secret: bytearray) -> UUID:
        try:
            if type(secret) is not bytearray or not 1 <= len(secret) <= SECRET_MAX_BYTES:
                raise ValueError("La clé ne respecte pas le format du coffre.")
            key = self.require_session(session_id)
            handle = uuid4()
            now = self.sessions.clock()
            expires = deadline(now, "real_contents")
            backend = self.keystore()
            with connect(self.path) as db:
                db.execute("INSERT INTO session_secrets VALUES (?, ?, ?, ?, 'sealing')",
                           (str(handle), key, stamp(now), stamp(expires)))
            try:
                with connect(self.path) as db:
                    self.require(db, key, handle, "sealing")
                    backend.put(handle, secret)
                    self.audit("vault.seal", "approved")
                    db.execute("UPDATE session_secrets SET state = 'live' WHERE handle = ?", (str(handle),))
            except Exception:
                self.discard(key, handle, backend)
                raise
            return handle
        finally:
            if isinstance(secret, bytearray):
                clear(secret)

    def handles(self, session_id: SessionId) -> tuple[UUID, ...]:
        key = self.require_session(session_id)
        with connect(self.path) as db:
            rows = db.execute("SELECT * FROM session_secrets WHERE session_id = ? ORDER BY created_at, handle",
                              (key,)).fetchall()
        handles = []
        for row in rows:
            handle = UUID(row["handle"])
            if row["state"] == "live" and not self.expired(row):
                handles.append(handle)
            elif row["state"] != "sealing" or self.sessions.clock() >= (
                datetime.fromisoformat(row["created_at"]) + timedelta(minutes=1)
            ):
                self.discard(key, handle, self.keystore())
        return tuple(handles)

    @contextmanager
    def resolve(self, session_id: SessionId, handle: UUID, *, approve):
        key = self.require_session(session_id)
        try:
            with connect(self.path) as db:
                self.require_live(db, key, handle)
            approved = approve() is True
        except MemoryRefusal:
            self.audit("vault.resolve", "denied")
            raise
        if not approved:
            self.audit("vault.resolve", "denied")
            raise MemoryRefusal("permission_denied", "Résolution du secret refusée.")
        value = None
        try:
            try:
                with connect(self.path) as db:
                    self.require_live(db, key, handle)
                    self.audit("vault.resolve", "approved")
                    value = self.keystore().get(handle)
            except (MemoryRefusal, KeyStoreUnavailable, SecretMissing):
                self.audit("vault.resolve", "failed")
                raise
            yield memoryview(value).toreadonly()
        finally:
            if value is not None:
                clear(value)

    def erase(self, session_id: SessionId, handle: UUID) -> None:
        key = self.require_session(session_id)
        with connect(self.path) as db:
            self.require(db, key, handle)
            db.execute("UPDATE session_secrets SET state = 'erasing' WHERE handle = ?", (str(handle),))
        self.discard(key, handle, self.keystore())
        self.audit("vault.erase", "approved")

    def discard(self, key: str, handle: UUID, backend) -> None:
        with connect(self.path) as db:
            row = db.execute("SELECT * FROM session_secrets WHERE session_id = ? AND handle = ?",
                             (key, str(handle))).fetchone()
            if row is not None and (row["state"] != "live" or self.expired(row)):
                backend.erase(handle)
                db.execute("DELETE FROM session_secrets WHERE handle = ?", (str(handle),))

    def expired(self, row) -> bool:
        created_at = datetime.fromisoformat(row["created_at"])
        expires_at = datetime.fromisoformat(row["expires_at"])
        return deadline(created_at, "real_contents", parent_deadlines=(expires_at,),
                        policy=load_policy()) <= self.sessions.clock()

    @staticmethod
    def require(db, key: str, handle: UUID, state=None):
        if not isinstance(handle, UUID):
            raise MemoryRefusal("permission_denied", "Référence de secret invalide.")
        row = db.execute("SELECT * FROM session_secrets WHERE session_id = ? AND handle = ?",
                         (key, str(handle))).fetchone()
        if row is None or (state is not None and row["state"] != state):
            raise MemoryRefusal("permission_denied", "Secret indisponible pour cette session.")
        return row

    def require_live(self, db, key: str, handle: UUID) -> None:
        if self.expired(self.require(db, key, handle, "live")):
            raise MemoryRefusal("retention_expired", "Ce secret a expiré.")
