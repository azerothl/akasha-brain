"""Métadonnées et faits admissibles des conversations locales."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NewType
from uuid import UUID, uuid4

from .memory_store import connect, stamp, utc_now
from .project_common import ProjectError, project_scope
from .retention import deadline, load_policy

SessionId = NewType("SessionId", UUID)

FACT_VALUES = {
    "summary_depth": frozenset({"standard", "detailed"}),
    "project_test": frozenset({"script", "unittest", "node", "none"}),
}
FACT_SOURCES = {"summary_depth": "operator_selection", "project_test": "project_inspection"}


@dataclass(frozen=True)
class GlobalMemoryRef:
    item_id: UUID


@dataclass(frozen=True)
class SessionMemoryRecord:
    kind: str
    value: str
    source: str
    project_scope: str | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ConversationSession:
    id: SessionId
    number: int
    projects: tuple[Path, ...]
    active_project: Path | None
    active_project_scope: str | None
    facts: tuple[SessionMemoryRecord, ...]
    global_memory: GlobalMemoryRef | None

    @property
    def title(self) -> str:
        return f"Session {self.number}"


class SessionStore:
    def __init__(self, path: Path, *, clock=utc_now, initialize=True):
        nominal = path.parent.resolve() / path.name
        if nominal.resolve() != nominal:
            raise ValueError("Le fichier de sessions doit être local et sans lien.")
        self.path = nominal
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if initialize:
            with connect(self.path, create=True) as db:
                self.create_schema(db)

    @staticmethod
    def create_schema(db):
        db.execute("""CREATE TABLE IF NOT EXISTS conversation_sessions (
            number INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
            active_project TEXT, global_item TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS conversation_session_projects (
            session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
            scope TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(session_id, scope)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS conversation_session_facts (
            session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
            scope TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, PRIMARY KEY(session_id, scope, kind)
        )""")

    @staticmethod
    def key(session_id: SessionId) -> str:
        if not isinstance(session_id, UUID):
            raise ValueError("Identifiant de session invalide.")
        return str(session_id)

    def create(self) -> SessionId:
        with connect(self.path) as db:
            return self.insert(db)

    def insert(self, db) -> SessionId:
        session_id = SessionId(uuid4())
        db.execute("INSERT INTO conversation_sessions(id, created_at) VALUES (?, ?)",
                   (self.key(session_id), stamp(self.clock())))
        return session_id

    def list(self) -> tuple[tuple[SessionId, int], ...]:
        with connect(self.path) as db:
            return self.entries(db)

    @staticmethod
    def entries(db) -> tuple[tuple[SessionId, int], ...]:
        rows = db.execute("SELECT id, number FROM conversation_sessions ORDER BY number")
        return tuple((SessionId(UUID(row["id"])), row["number"]) for row in rows)

    def startup(self) -> tuple[tuple[tuple[SessionId, int], ...], ConversationSession]:
        with connect(self.path, create=True) as db:
            self.create_schema(db)
            entries = self.entries(db)
            if not entries:
                self.insert(db)
                entries = self.entries(db)
            return entries, self.snapshot(db, entries[-1][0])

    def bind_project(self, session_id: SessionId, selected: Path) -> None:
        project = selected.resolve(strict=True)
        if self.path.is_relative_to(project):
            raise ValueError("Choisissez un projet qui ne contient pas le registre des sessions.")
        scope = project_scope(project)
        key = self.key(session_id)
        with connect(self.path) as db:
            self.require(db, key)
            db.execute("INSERT OR IGNORE INTO conversation_session_projects VALUES (?, ?, ?)",
                       (key, scope, str(project)))
            db.execute("UPDATE conversation_sessions SET active_project = ? WHERE id = ?", (scope, key))

    def link_global(self, session_id: SessionId, reference: GlobalMemoryRef | None) -> None:
        """Conserve uniquement un identifiant. La lecture reste soumise à la politique de mémoire."""
        key = self.key(session_id)
        if reference is not None and (not isinstance(reference, GlobalMemoryRef)
                                      or not isinstance(reference.item_id, UUID)):
            raise ValueError("Référence de mémoire invalide.")
        with connect(self.path) as db:
            self.require(db, key)
            db.execute("UPDATE conversation_sessions SET global_item = ? WHERE id = ?",
                       (str(reference.item_id) if reference is not None else None, key))

    def remember(self, session_id: SessionId, kind: str, value: str, *, project: Path | None = None) -> None:
        allowed = FACT_VALUES.get(kind)
        if allowed is None or type(value) is not str or value not in allowed:
            raise ValueError("Fait de session hors du schéma autorisé.")
        if (kind == "project_test") != (project is not None):
            raise ValueError("Périmètre de fait invalide.")
        key = self.key(session_id)
        scope = project_scope(project) if project is not None else ""
        now = self.clock()
        expires = deadline(now, "minimized_results")
        with connect(self.path) as db:
            self.require(db, key)
            if scope and db.execute("""SELECT 1 FROM conversation_session_projects
                                  WHERE session_id = ? AND scope = ?""", (key, scope)).fetchone() is None:
                raise ValueError("Projet hors de la session.")
            db.execute("""INSERT INTO conversation_session_facts VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(session_id, scope, kind) DO UPDATE SET value = excluded.value,
                       created_at = excluded.created_at, expires_at = excluded.expires_at""",
                       (key, scope, kind, value, stamp(now), stamp(expires)))

    def open(self, session_id: SessionId) -> ConversationSession:
        with connect(self.path) as db:
            return self.snapshot(db, session_id)

    def snapshot(self, db, session_id: SessionId) -> ConversationSession:
        key = self.key(session_id)
        now = self.clock()
        policy = load_policy()
        record = self.require(db, key)
        projects = self.bound_projects(db, key)
        facts = []
        rows = db.execute("SELECT * FROM conversation_session_facts WHERE session_id = ? ORDER BY kind, scope",
                          (key,)).fetchall()
        for row in rows:
            created = datetime.fromisoformat(row["created_at"])
            expires = deadline(created, "minimized_results",
                               parent_deadlines=(datetime.fromisoformat(row["expires_at"]),), policy=policy)
            allowed = FACT_VALUES.get(row["kind"], ())
            if expires <= now or row["value"] not in allowed or (row["scope"] and row["scope"] not in projects):
                db.execute("DELETE FROM conversation_session_facts WHERE session_id = ? AND scope = ? AND kind = ?",
                           (key, row["scope"], row["kind"]))
                continue
            facts.append(SessionMemoryRecord(row["kind"], row["value"], FACT_SOURCES[row["kind"]],
                                             row["scope"] or None, created, expires))
        link = GlobalMemoryRef(UUID(record["global_item"])) if record["global_item"] else None
        scope = record["active_project"] if record["active_project"] in projects else None
        return ConversationSession(session_id, record["number"], tuple(projects.values()),
                                   projects.get(scope), scope, tuple(facts), link)

    @staticmethod
    def bound_projects(db, key: str) -> dict[str, Path]:
        projects = {}
        for row in db.execute("SELECT scope, path FROM conversation_session_projects WHERE session_id = ? ORDER BY path",
                              (key,)):
            path = Path(row["path"])
            try:
                if path.is_absolute() and path.resolve(strict=True) == path and project_scope(path) == row["scope"]:
                    projects[row["scope"]] = path
            except (OSError, ProjectError):
                continue
        return projects

    @staticmethod
    def require(db, key: str):
        record = db.execute("SELECT * FROM conversation_sessions WHERE id = ?", (key,)).fetchone()
        if record is None:
            raise ValueError("Session introuvable.")
        return record
