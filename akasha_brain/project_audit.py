"""Journal minimal des décisions sur le projet réel, séparé de ses artefacts."""

from datetime import datetime, timezone
import json
from pathlib import Path

from .experience import transaction
from .project_common import digest

LOG_NAME = "akasha-audit.sqlite"
POLICY_VERSION = "brain-system-spec@0.16/13.6"
CAPABILITY_VERSION = "1.0.0"


def record(directory: Path, *, action: str, risk: str, actor: str, decision: str, reason: str | None = None) -> None:
    with transaction(directory.parent / LOG_NAME) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS decisions (
            seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL
        )""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS no_edit_decisions BEFORE UPDATE ON decisions
            BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS no_delete_decisions BEFORE DELETE ON decisions
            BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
        previous = db.execute("SELECT digest FROM decisions ORDER BY seq DESC LIMIT 1").fetchone()
        event = {"created_at": datetime.now(timezone.utc).isoformat(), "actor": actor, "risk_class": risk,
                 "action": action, "decision": decision, "reason": reason, "policy_version": POLICY_VERSION,
                 "capability_version": CAPABILITY_VERSION, "previous": previous[0] if previous else None}
        payload = json.dumps(event, ensure_ascii=True, sort_keys=True)
        db.execute("INSERT INTO decisions (payload, digest) VALUES (?, ?)",
                   (payload, digest(payload.encode("utf-8"))))


def verify(path: Path) -> dict:
    path = path.resolve(strict=True)
    with transaction(path) as db:
        rows = db.execute("SELECT seq, payload, digest FROM decisions ORDER BY seq").fetchall()
    previous = None
    for expected, (seq, payload, signature) in enumerate(rows, start=1):
        event = json.loads(payload)
        if seq != expected or event["previous"] != previous or digest(payload.encode("utf-8")) != signature:
            return {"status": "failed", "entries_verified": expected - 1, "invalid_entry": seq}
        previous = signature
    return {"status": "passed", "entries_verified": len(rows)}
