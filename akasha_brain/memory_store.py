"""Stockage effaçable et contrôle de filiation de la mémoire locale."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from . import project_audit
from .retention import deadline, load_policy


class MemoryRefusal(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Un instant avec fuseau est requis.")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


@contextmanager
def connect(path: Path, *, create: bool = False):
    mode = "rwc" if create else "rw"
    with closing(sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=10)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA secure_delete = ON")
        if db.execute("PRAGMA journal_mode = DELETE").fetchone()[0] != "delete":
            raise MemoryRefusal("storage_unverified", "Le journal SQLite doit être effaçable.")
        db.execute("BEGIN IMMEDIATE")
        yield db


def related(db, item_id: str, *, ancestors: bool) -> list[str]:
    source, target = ("child", "parent") if ancestors else ("parent", "child")
    return [row[0] for row in db.execute(f"""WITH RECURSIVE family(id) AS (
        SELECT ? UNION SELECT lineage.{target} FROM memory_lineage AS lineage
        JOIN family ON lineage.{source} = family.id
    ) SELECT id FROM family""", (item_id,))]


def row_for(db, item_id: str):
    return db.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()


def expiration(row, policy) -> datetime:
    return deadline(datetime.fromisoformat(row["created_at"]), row["retention"],
                    parent_deadlines=(datetime.fromisoformat(row["expires_at"]),), policy=policy)


class MemoryStore:
    def __init__(self, path: Path, *, clock=utc_now):
        self.path = path.resolve()
        self.control = self.path.with_name(f"{self.path.name}.memory-control.sqlite")
        self.clock = clock

    def configured(self) -> bool:
        if not self.path.is_file():
            return False
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as db:
            return db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'memory_identity'").fetchone() is not None

    def enabled(self, control) -> bool:
        if not control.execute("SELECT 1 FROM sqlite_schema WHERE name = 'memory_workflow_registry'").fetchone():
            return True
        flag = control.execute("SELECT enabled FROM memory_workflow_registry WHERE singleton = 1").fetchone()
        return flag is not None and bool(flag[0])

    def require_enabled(self, control) -> None:
        if not self.enabled(control):
            raise MemoryRefusal("memory_disabled", "La mémoire est désactivée.")

    def initialize(self) -> None:
        if self.control.exists():
            with self.access():
                return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Une base déjà liée ne doit jamais recevoir un registre vide en remplacement.
        with connect(self.path, create=True) as db:
            if db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'memory_identity'").fetchone():
                raise MemoryRefusal("ledger_unverified", "Registre d'effacement manquant.")
        self.control.touch(exist_ok=False)
        with connect(self.control) as control, connect(self.path) as db:
            identity = str(uuid4())
            control.execute("CREATE TABLE memory_identity (id TEXT PRIMARY KEY)")
            control.execute("INSERT INTO memory_identity VALUES (?)", (identity,))
            control.execute("""CREATE TABLE memory_erasures (
                id TEXT PRIMARY KEY, requested_at TEXT NOT NULL, reason TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0, is_trace INTEGER NOT NULL
            )""")
            db.execute("CREATE TABLE memory_identity (id TEXT PRIMARY KEY)")
            db.execute("INSERT INTO memory_identity VALUES (?)", (identity,))
            db.execute("""CREATE TABLE memory_items (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL, retention TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE memory_lineage (
                child TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                parent TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                PRIMARY KEY (child, parent)
            )""")
            db.execute("CREATE INDEX memory_descendants ON memory_lineage (parent)")
            db.execute("CREATE INDEX memory_kind ON memory_items (scope, kind, created_at, id)")

    @contextmanager
    def access(self):
        if not self.control.is_file() or self.control.resolve() != self.control:
            raise MemoryRefusal("ledger_unverified", "Registre d'effacement indisponible.")
        with connect(self.control) as control, connect(self.path) as db:
            try:
                expected = control.execute("SELECT id FROM memory_identity").fetchall()
                actual = db.execute("SELECT id FROM memory_identity").fetchall()
                control.execute("SELECT id, verified, is_trace FROM memory_erasures LIMIT 0")
            except sqlite3.DatabaseError as error:
                raise MemoryRefusal("ledger_unverified", "Registre d'effacement invérifiable.") from error
            if len(expected) != 1 or expected != actual:
                raise MemoryRefusal("ledger_unverified", "Registre d'effacement incompatible.")
            yield control, db

    def require(self, control, db, item_id: str, *, scope: str, now: datetime, policy):
        row = row_for(db, item_id)
        if row is not None and row["scope"] != scope:
            raise MemoryRefusal("out_of_scope", "Objet hors du périmètre demandé.")
        for ancestor in related(db, item_id, ancestors=True):
            marker = control.execute("SELECT is_trace FROM memory_erasures WHERE id = ?", (ancestor,)).fetchone()
            if marker:
                if (row is not None and row["kind"] == "trace") or (ancestor == item_id and marker["is_trace"]):
                    raise MemoryRefusal("redacted_by_deletion", "Trace expurgée. Rejeu indisponible.")
                raise MemoryRefusal("erasure_requested", "Objet en cours d'effacement ou effacé.")
            source = row_for(db, ancestor)
            if source is None:
                raise MemoryRefusal("missing_object", "Objet ou source introuvable.")
            if expiration(source, policy) <= now:
                raise MemoryRefusal("retention_expired", "La durée de rétention est écoulée.")
            if source["kind"] == "project_reference":
                from .project_memory import require_reference

                require_reference(db, source, now, trace=row["kind"] == "trace")
        return row

    def save(self, control, db, *, kind: str, scope: str, payload, now: datetime, policy,
             parents=(), item_id: str | None = None, created_at: datetime | None = None,
             prior_deadline: datetime | None = None, retention: str = "minimized_results") -> str:
        item_id = item_id or str(uuid4())
        if control.execute("SELECT 1 FROM memory_erasures WHERE id = ?", (item_id,)).fetchone():
            raise MemoryRefusal("erasure_requested", "L'objet a déjà fait l'objet d'une demande d'effacement.")
        limits = [expiration(self.require(control, db, parent, scope=scope, now=now, policy=policy), policy)
                  for parent in dict.fromkeys(parents)]
        if prior_deadline is not None:
            limits.append(prior_deadline)
        created_at = now if created_at is None else created_at
        expires = deadline(created_at, retention, parent_deadlines=limits, policy=policy)
        if expires <= now:
            raise MemoryRefusal("retention_expired", "La durée de rétention est écoulée.")
        db.execute("INSERT INTO memory_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (item_id, kind, scope, encode(payload), stamp(created_at), stamp(expires), retention))
        db.executemany("INSERT INTO memory_lineage VALUES (?, ?)", ((item_id, parent) for parent in dict.fromkeys(parents)))
        return item_id

    def mark(self, control, db, item_id: str, reason: str, now: datetime) -> int:
        changed = 0
        for member in related(db, item_id, ancestors=False):
            row = row_for(db, member)
            if row is None:
                continue
            changed += control.execute("INSERT OR IGNORE INTO memory_erasures VALUES (?, ?, ?, 0, ?)",
                                       (member, stamp(now), reason, row["kind"] == "trace")).rowcount
        return changed

    def request_erasure(self, item_id: str) -> None:
        from .memory_backup import archived_kind

        with self.access() as (control, db):
            exists = control.execute("SELECT 1 FROM memory_erasures WHERE id = ?", (item_id,)).fetchone()
            row = row_for(db, item_id)
            if not exists and row is None:
                is_trace = archived_kind(self, control, item_id)
                if is_trace is None:
                    raise MemoryRefusal("missing_object", "Objet introuvable.")
                control.execute("INSERT INTO memory_erasures VALUES (?, ?, 'user_request', 0, ?)",
                                (item_id, stamp(self.clock()), is_trace))
            if row is not None and row["kind"] == "project_reference":
                raise MemoryRefusal("project_erasure_required", "Utilisez l'effacement du projet pour traiter le contenu source.")
            changed = self.mark(control, db, item_id, "user_request", self.clock()) or (not exists and row is None)
        if changed:
            self.audit_erasure("requested")

    def finish_erasures(self) -> dict:
        from .memory_backup import include_backup_descendants, purge_keys
        from .memory_scratch import recover_scratch

        with self.access() as (control, db):
            ids = [row[0] for row in control.execute("SELECT id FROM memory_erasures WHERE verified = 0")]
            include_backup_descendants(self, control, db, ids)
            prepared = {row[0] for row in control.execute("SELECT id FROM memory_erasures WHERE verified = 0")}
        with self.access() as (control, db):
            ids = [row[0] for row in control.execute("SELECT id FROM memory_erasures WHERE verified = 0")]
            if not set(ids) <= prepared:
                raise MemoryRefusal("erasure_pending", "Une nouvelle demande d'effacement est en attente.")
            recover_scratch(self, db, ids)
            purge_keys(self, control, ids)
            db.executemany("DELETE FROM memory_items WHERE id = ?", ((item,) for item in ids))
            db.commit()
            # Vérifier après le commit qui supprime les contenus et les liens.
            db.execute("BEGIN IMMEDIATE")
            if (db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or db.execute("PRAGMA foreign_key_check").fetchone() is not None
                    or any(row_for(db, item) is not None for item in ids)
                    or any(self.path.with_name(f"{self.path.name}{suffix}").exists()
                           for suffix in ("-journal", "-wal", "-shm"))):
                raise MemoryRefusal("erasure_pending", "La vérification SQLite de l'effacement est en attente.")
            if ids:
                if control.execute("SELECT 1 FROM sqlite_schema WHERE name = 'memory_skill_state'").fetchone():
                    control.executemany("DELETE FROM memory_skill_state WHERE workflow = ?", ((item,) for item in ids))
                self.audit_erasure("verified")
                control.execute("UPDATE memory_erasures SET verified = 1 WHERE verified = 0")
        return {"status": "verified", "removed": len(ids)}

    def expire(self) -> dict:
        from .memory_backup import mark_archived_expiry

        policy = load_policy()
        with self.access() as (control, db):
            now = self.clock()
            changed = sum(self.mark(control, db, row["id"], "expired", now)
                          for row in db.execute("SELECT * FROM memory_items")
                          if expiration(row, policy) <= now)
        if changed:
            self.audit_erasure("expired")
        with self.access() as (control, _):
            archived = mark_archived_expiry(self, control, now, policy)
        if archived:
            self.audit_erasure("expired")
        return self.finish_erasures()

    def audit_erasure(self, decision: str) -> None:
        project_audit.record(self.path, action="memory_erasure", risk="R3",
                             actor="user" if decision == "requested" else "policy", decision=decision)
