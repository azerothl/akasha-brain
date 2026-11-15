"""Consentement local à la réutilisation de contenus dans l'évolution."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from contracts.akasha_contracts.validate import validate

from .experience import transaction
from .planning import PlanningError
from .project_common import ProjectError, project_scope

PURPOSE = "local_evolution"
CATEGORIES = (
    "user_requests", "assistant_responses", "source_code", "diffs",
    "test_outputs", "screenshots", "ocr", "user_comments",
)


@dataclass(frozen=True)
class ReuseScope:
    """Périmètre d'une source identifié par l'adaptateur, avec son accord exact."""

    project: str
    category: str
    consent_id: str | None
    provenance: str
    contains_secrets: bool | None


def instant(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is not None:
            return moment.astimezone(timezone.utc)
    except ValueError:
        pass
    raise PlanningError(AkashaError(ErrorCode.CONTRACT_SCHEMA_VIOLATION, "Un instant avec fuseau est requis."))


def timestamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def refusal(code: ErrorCode, reason: str, message: str) -> AkashaError:
    return AkashaError(code, message, {"reason": reason})


def validate_consent(document: dict) -> None:
    if errors := validate(document, "EvolutionConsent"):
        raise PlanningError(errors[0])
    categories = document["categories"]
    if (document["project"].strip() != document["project"] or not document["project"].strip()
            or len(set(categories)) != len(categories) or any(category not in CATEGORIES for category in categories)
            or document["purpose"] != PURPOSE):
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Périmètre de consentement invalide."))
    granted_at = instant(document["granted_at"])
    if document.get("expires_at") is not None and instant(document["expires_at"]) <= granted_at:
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'échéance doit suivre l'accord."))


def grant(path: Path, project: str, categories: list[str], expires_at: str | None = None) -> dict:
    document = {"project": project, "categories": categories, "purpose": PURPOSE,
                "granted_at": timestamp(datetime.now(timezone.utc)),
                "expires_at": timestamp(instant(expires_at)) if expires_at is not None else None, "status": "active"}
    validate_consent(document)
    consent_id = str(uuid4())
    with transaction(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS evolution_consents (
            consent_id TEXT PRIMARY KEY, document TEXT NOT NULL
        )""")
        db.execute("INSERT INTO evolution_consents VALUES (?, ?)", (consent_id, json.dumps(document)))
    return {"consent_id": consent_id, **document}


def has_registry(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'evolution_consents'").fetchone() is not None


def load_consent(db: sqlite3.Connection, consent_id: str) -> dict | None:
    if not has_registry(db):
        return None
    row = db.execute("SELECT document FROM evolution_consents WHERE consent_id = ?", (consent_id,)).fetchone()
    if row is None:
        return None
    document = json.loads(row[0])
    validate_consent(document)
    return document


def revoke(path: Path, consent_id: str) -> dict:
    missing = refusal(ErrorCode.APPROVAL_REQUIRED, "consent_missing", "Accord d'évolution introuvable.")
    if not path.is_file():
        raise PlanningError(missing)
    with transaction(path) as db:
        db.execute("BEGIN IMMEDIATE")
        document = load_consent(db, consent_id)
        if document is None:
            raise PlanningError(missing)
        if document["status"] != "revoked":
            document["status"] = "revoked"
            db.execute("UPDATE evolution_consents SET document = ? WHERE consent_id = ?",
                       (json.dumps(document), consent_id))
    return {"consent_id": consent_id, **document}


def list_consents(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with transaction(path) as db:
        if not has_registry(db):
            return []
        return [{"consent_id": consent_id, **json.loads(document)}
                for consent_id, document in db.execute("SELECT consent_id, document FROM evolution_consents ORDER BY rowid")]


def check_reuse(db: sqlite3.Connection, scopes: tuple[ReuseScope, ...], *, now: datetime | None = None) -> AkashaError | None:
    """Vérifie toutes les sources au moment de leur utilisation, hors modèle."""
    moment = now or datetime.now(timezone.utc)
    for scope in scopes:
        if (scope.provenance != "project" or scope.contains_secrets is not False
                or not scope.project or scope.category not in CATEGORIES):
            return refusal(ErrorCode.PERMISSION_DENIED, "data_excluded", "Provenance ou contenu exclu de l'évolution.")
        try:
            document = load_consent(db, scope.consent_id) if scope.consent_id is not None else None
        except (PlanningError, json.JSONDecodeError):
            return refusal(ErrorCode.PERMISSION_DENIED, "consent_invalid", "Consentement enregistré invalide.")
        if document is None:
            return refusal(ErrorCode.APPROVAL_REQUIRED, "consent_missing", "Consentement explicite requis.")
        if document["project"] != scope.project or scope.category not in document["categories"]:
            return refusal(ErrorCode.PERMISSION_DENIED, "consent_scope_mismatch", "Projet ou catégorie hors périmètre.")
        if document["status"] == "revoked":
            return refusal(ErrorCode.PERMISSION_DENIED, "consent_revoked", "Consentement révoqué.")
        expires_at = document.get("expires_at")
        if moment < instant(document["granted_at"]) or (expires_at is not None and moment >= instant(expires_at)):
            return refusal(ErrorCode.PERMISSION_DENIED, "consent_inactive", "Consentement hors de sa période de validité.")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Registre SQLite de l'évolution locale")
    commands = parser.add_subparsers(dest="command", required=True)
    allow = commands.add_parser("grant", help="Accorder une réutilisation pour l'évolution locale")
    project = allow.add_mutually_exclusive_group(required=True)
    project.add_argument("--project")
    project.add_argument("--project-root", type=Path, help="Dossier du parcours projet local")
    allow.add_argument("--category", action="append", required=True, choices=CATEGORIES)
    allow.add_argument("--expires-at")
    withdraw = commands.add_parser("revoke", help="Révoquer un consentement")
    withdraw.add_argument("--consent", required=True)
    commands.add_parser("status", help="Consulter les consentements")
    check = commands.add_parser("check", help="Vérifier le périmètre déclaré d'une source")
    project = check.add_mutually_exclusive_group(required=True)
    project.add_argument("--project")
    project.add_argument("--project-root", type=Path)
    check.add_argument("--category", required=True)
    check.add_argument("--consent")
    check.add_argument("--provenance", required=True, choices=("project", "transfer", "unknown"))
    check.add_argument("--contains-secrets", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "grant":
            project = project_scope(args.project_root) if args.project_root is not None else args.project
            result = grant(args.db, project, args.category, args.expires_at)
        elif args.command == "revoke":
            result = revoke(args.db, args.consent)
        elif args.command == "status":
            result = {"consents": list_consents(args.db)}
        else:
            project = project_scope(args.project_root) if args.project_root is not None else args.project
            scope = ReuseScope(project, args.category, args.consent, args.provenance, args.contains_secrets)
            with transaction(args.db if args.db.is_file() else Path(":memory:")) as db:
                denied = check_reuse(db, (scope,))
            if denied:
                raise PlanningError(denied)
            result = {"status": "allowed", "purpose": PURPOSE}
    except (PlanningError, ProjectError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        error = (exc.error if isinstance(exc, (PlanningError, ProjectError))
                 else AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(exc)))
        print(json.dumps({"status": "refused", "error": error.as_dict()}, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
