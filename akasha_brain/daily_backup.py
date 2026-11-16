"""Sauvegarde locale quotidienne d'un projet et rotation de ses archives gérées."""

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import stat
from time import sleep
from uuid import UUID

from contracts.akasha_contracts.errors import ErrorCode

from .evolution_consent import instant
from .experience import prune_experiences, transaction
from .planning import PlanningError
from .project import project_lease
from .project_backup import backup
from .project_backup_vault import configured_vault, crypto, decode, table_exists, vault_path, verify_head
from .project_common import ProjectError, digest, identity, project_scope, reject
from .project_evolution import expire_copies, registry_path
from .retention import deadline, load_policy


def archive_root(project: Path, directory: Path, scope: str) -> Path:
    root = directory.resolve() / scope.removeprefix("local-project:")
    if root.resolve() != root or root.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "Le dossier d’archives doit être distinct du projet et sans redirection.")
    return root


def read_metadata(seal: str, scope: str, day: str) -> dict:
    entry = json.loads(decode(crypto("unseal", data=seal)["data"]))
    if (entry["project"] != scope or entry["day"] != day or instant(entry["created_at"]).date().isoformat() != day
            or date.fromisoformat(day).isoformat() != day or str(UUID(entry["backup_id"])) != entry["backup_id"]):
        reject(ErrorCode.PERMISSION_DENIED, "Inventaire des sauvegardes quotidien incompatible.", reason="ledger_unverified")
    return entry


def archive_matches(path: Path, checksum: str) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or path.resolve() != path or digest(path.read_bytes()) != checksum):
        reject(ErrorCode.PERMISSION_DENIED, "Le fichier d’archive ne correspond plus à l’inventaire.",
               reason="copy_unreachable")
    return True


def discard_keys(vault, scope: str, backup_id: str) -> None:
    vault.execute("PRAGMA secure_delete = ON")
    vault.execute("DELETE FROM backup_keys WHERE project = ? AND backup_id = ?", (scope, backup_id))
    vault.commit()
    if (vault.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            and vault.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]):
        reject(ErrorCode.PERMISSION_DENIED, "La purge des clés reste en attente.", reason="key_unavailable")


def rotate(project: Path, registry: Path, root: Path, scope: str, now: datetime, policy: dict) -> dict:
    rotation = {"current": None, "removed": [], "pending": []}
    today = now.date().isoformat()
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        vault_id = configured_vault(grants, scope)
        if vault_id is None:
            return rotation
        path = vault_path(project, registry)
        if not path.is_file():
            reject(ErrorCode.PERMISSION_DENIED, "Le coffre des archives est indisponible.", reason="ledger_unverified")
        with transaction(path) as vault:
            verify_head(grants, vault, scope, vault_id)
            if not table_exists(vault, "daily_archives"):
                return rotation
            records = vault.execute("SELECT day, seal FROM daily_archives WHERE project = ? ORDER BY day", (scope,)).fetchall()
            for day, seal in records:
                entry = read_metadata(seal, scope, day)
                expected = root / f"{day}.backup"
                if Path(entry["path"]) != expected:
                    reject(ErrorCode.PERMISSION_DENIED, "Le dossier des archives gérées a changé.",
                           reason="ledger_unverified")
                due = deadline(instant(entry["created_at"]), "backup",
                               parent_deadlines=(instant(entry["expires_at"]),), policy=policy)
                expired = now >= due
                try:
                    if expired:
                        discard_keys(vault, scope, entry["backup_id"])
                    try:
                        present = archive_matches(expected, entry["sha256"])
                    except ProjectError:
                        if not expired:
                            raise
                        rotation["pending"].append({"day": day, "reason": "copy_unreachable"})
                        continue
                    if present and not expired:
                        if day == today:
                            rotation["current"] = entry["backup_id"]
                        continue
                    if present:
                        expected.unlink()
                        if expected.exists():
                            raise OSError("L’archive existe encore après la rotation.")
                    if not expired:
                        # La publication a pu être interrompue après l'enregistrement des clés.
                        discard_keys(vault, scope, entry["backup_id"])
                    vault.execute("DELETE FROM daily_archives WHERE project = ? AND day = ?", (scope, day))
                    vault.commit()
                    rotation["removed"].append(day)
                except (OSError, sqlite3.Error, ProjectError) as error:
                    reason = error.error.details.get("reason", "copy_unreachable") if isinstance(error, ProjectError) else "copy_unreachable"
                    rotation["pending"].append({"day": day, "reason": reason})
    return rotation


def run_daily(project: Path, registry: Path, directory: Path, consent: str) -> dict:
    project = project.resolve(strict=True)
    registry = registry_path(project, registry)
    scope = project_scope(project)
    root = archive_root(project, directory, scope)
    now = datetime.now(timezone.utc)
    policy = load_policy()
    with project_lease(identity(project)):
        erasures = expire_copies(project, registry, now=now)
        experiences = prune_experiences(registry, now=now)
        rotation = rotate(project, registry, root, scope, now, policy)
        output = root / f"{now.date().isoformat()}.backup"
        if rotation["current"] is not None:
            result = {"status": "already_backed_up", "backup_id": rotation["current"], "archive": str(output)}
        elif not policy["backup"]["daily"]:
            result = {"status": "disabled_by_policy"}
        elif any(item["day"] == now.date().isoformat() for item in rotation["pending"]):
            result = {"status": "pending"}
        else:
            result = {**backup(project, registry, output, consent, daily=True), "archive": str(output)}
    return {**result, "rotated": rotation["removed"], "pending_rotation": rotation["pending"],
            "expired_experiences": experiences, "erasures": erasures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--consent", required=True)
    parser.add_argument("--watch", action="store_true", help="Exécuter chaque jour UTC tant que le processus reste actif")
    args = parser.parse_args()
    last_message = None
    while True:
        try:
            result = run_daily(args.project, args.db, args.output_dir, args.consent)
            pending = result["pending_rotation"] or any(item["status"] == "pending" for item in result["erasures"])
            outcome = 1 if pending else 0
        except (OSError, sqlite3.Error, PlanningError, ProjectError, ValueError, KeyError) as error:
            result = {"status": "failed", "error": str(error)}
            outcome = 1
        message = json.dumps(result, ensure_ascii=False)
        if message != last_message:
            print(message, flush=True)
            last_message = message
        if not args.watch:
            return outcome
        sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
