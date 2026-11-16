"""Échéance et checkpoint effaçable d'une proposition de projet."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

from contracts.akasha_contracts.errors import ErrorCode

from .experience import transaction
from .project_common import digest, reject

APPROVAL_WINDOW = timedelta(minutes=30)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_request() -> dict:
    issued = utc_now()
    return {"id": str(uuid4()), "issued_at": issued.isoformat(),
            "expires_at": (issued + APPROVAL_WINDOW).isoformat()}


def approval_deadline(manifest: dict, path: Path) -> datetime:
    if "approval" not in manifest:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) + APPROVAL_WINDOW
    request = manifest["approval"]
    UUID(request["id"])
    issued = datetime.fromisoformat(request["issued_at"])
    expires = datetime.fromisoformat(request["expires_at"])
    if issued.utcoffset() is None or expires.utcoffset() is None or not timedelta() < expires - issued <= APPROVAL_WINDOW:
        raise ValueError("Échéance d'approbation invalide.")
    return expires


def expired(expires_at: datetime) -> bool:
    return utc_now() >= expires_at


def require_fresh(expires_at: datetime) -> None:
    if expired(expires_at):
        reject(ErrorCode.APPROVAL_EXPIRED, "Approbation expirée. Demandez un nouvel accord avant l'application.",
               expires_at=expires_at.isoformat())


def action_key(manifest: dict) -> str:
    action = {key: value for key, value in manifest.items() if key != "approval"}
    return digest(json.dumps(action, sort_keys=True).encode("utf-8"))


def application_state(proposal: Path, key: str) -> str | None:
    path = proposal / "application.sqlite"
    if not path.is_file():
        return None
    with transaction(path) as db:
        row = db.execute("SELECT state FROM effects WHERE action_key = ?", (key,)).fetchone()
    return row[0] if row else None


def mark_application(proposal: Path, key: str, state: str) -> None:
    with transaction(proposal / "application.sqlite") as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS effects (
            action_key TEXT PRIMARY KEY, state TEXT NOT NULL CHECK (state IN ('applying', 'applied'))
        )""")
        db.execute("""INSERT INTO effects VALUES (?, ?)
            ON CONFLICT (action_key) DO UPDATE SET state = excluded.state""", (key, state))


def discard_unstarted_application(proposal: Path, key: str) -> None:
    with transaction(proposal / "application.sqlite") as db:
        db.execute("DELETE FROM effects WHERE action_key = ? AND state = 'applying'", (key,))
