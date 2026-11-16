"""Copie effaçable et relecture contrôlée de propositions projet validées."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import stat
from uuid import UUID, uuid4

from bench.run_guided_repair import BENCH
from contracts.akasha_contracts.errors import ErrorCode

from .evolution_consent import ReuseScope, check_reuse, timestamp
from .experience import transaction
from .project_audit import record as audit_decision
from .project_backup_vault import sync_erasures, table_exists
from .project_common import ProjectError, digest, identity, project_scope, reject
from .retention import copy_deadline, deadline, load_policy

ARTIFACTS = {"source_code": ("replacement.txt", "replacement_sha256"), "diffs": ("proposal.diff", "diff_sha256")}


@dataclass(frozen=True)
class ProjectSample:
    sample_id: str
    scope: ReuseScope
    manifest: dict
    payload: bytes
    created_at: str
    expires_at: str


def registry_path(project: Path, registry: Path, *, require_existing: bool = True) -> Path:
    path = registry.resolve()
    if path.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "Le registre d'évolution doit être hors du projet.")
    if require_existing and not path.is_file():
        reject(ErrorCode.APPROVAL_REQUIRED, "Consentement explicite requis.", reason="consent_missing")
    return path


def content_path(project: Path, registry: Path) -> Path:
    path = registry.with_name(registry.name + ".project-content.sqlite").resolve()
    if path.is_relative_to(project) or path == registry:
        reject(ErrorCode.PERMISSION_DENIED, "Le stockage des contenus doit être distinct du projet et du registre.")
    return path


def require_consent(db, scope: ReuseScope) -> None:
    if denied := check_reuse(db, (scope,)):
        raise ProjectError(denied)


def ensure_samples(db) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS samples (
        sample_id TEXT PRIMARY KEY, project TEXT NOT NULL, category TEXT NOT NULL,
        consent_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        manifest TEXT NOT NULL, payload BLOB NOT NULL
    )""")


def erasure_marker(db, project: str, *, sample_id: str | None = None, source_id: str | None = None):
    if not db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'project_erasures' AND type = 'table'").fetchone():
        return None
    return db.execute("""SELECT request_id, state, reason FROM project_erasures
                         WHERE project = ? AND (sample_id = ? OR source_id = ?) LIMIT 1""",
                      (project, sample_id, source_id)).fetchone()


def require_not_erased(db, project: str, *, sample_id: str | None = None, source_id: str | None = None) -> None:
    if erasure_marker(db, project, sample_id=sample_id, source_id=source_id):
        reject(ErrorCode.PERMISSION_DENIED, "Cette copie est bloquée par une demande d'effacement.",
               reason="content_erasure_requested")


def require_sample(db, sample: ProjectSample) -> None:
    require_not_erased(db, sample.scope.project, sample_id=sample.sample_id, source_id=sample.manifest.get("source_id"))
    require_consent(db, sample.scope)
    if datetime.now(timezone.utc) >= copy_deadline(sample.created_at, sample.expires_at):
        reject(ErrorCode.PERMISSION_DENIED, "La copie a expiré.", reason="content_expired")


def check_sample(project: Path, registry: Path, sample: ProjectSample) -> None:
    with transaction(registry_path(project, registry)) as db:
        require_sample(db, sample)


def collect(project: Path, proposal: Path, registry: Path, category: str, consent_id: str | None,
            reviewed_digest: str | None) -> dict:
    project = project.resolve(strict=True)
    registry = registry_path(project, registry)
    proposal = proposal.resolve(strict=True)
    encoded = (proposal / "proposal.json").read_bytes()
    manifest = json.loads(encoded)
    if identity(project) != manifest["project"]:
        reject(ErrorCode.PERMISSION_DENIED, "Proposition d'un autre projet.", reason="consent_scope_mismatch")
    validation = manifest["validation"]
    if (manifest["version"] not in (1, 2) or manifest.get("operation", "replace") != "replace"
            or validation["status"] != "passed" or validation["guest_exit_code"] != 0x4700
            or validation.get("sandbox_stopped") is not True or validation.get("read_only_input") is not True):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Une proposition de remplacement validée dans le bac est requise.")
    if category not in ARTIFACTS:
        reject(ErrorCode.PERMISSION_DENIED, "Catégorie de collecte exclue.", reason="data_excluded")
    if (project / manifest["target"]).resolve().is_relative_to(BENCH.resolve()):
        reject(ErrorCode.PERMISSION_DENIED, "Les artefacts du banc sont exclus de cette collecte.", reason="data_excluded")
    reviewed = reviewed_digest == digest(encoded)
    scope = ReuseScope(project_scope(project), category, consent_id, "project", False if reviewed else None)
    filename, checksum = ARTIFACTS[category]
    sample_id = str(uuid4())
    replay = {key: manifest[key] for key in ("project", "target", "test", "files", "diff_sha256", "replacement_sha256")}
    replay["dependency_requests"] = [wheel["request_sha256"] for wheel in manifest.get("dependencies", [])]
    replay["proposal_sha256"] = reviewed_digest
    replay["source_id"] = str(UUID(validation["sandbox_id"]))

    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        require_not_erased(grants, scope.project, source_id=replay["source_id"])
        require_consent(grants, scope)
        payload = (proposal / filename).read_bytes()
        if digest(payload) != manifest[checksum]:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'artefact diffère de la proposition examinée.")
        created = datetime.now(timezone.utc)
        expires_at = timestamp(deadline(created, "real_contents"))
        with transaction(content_path(project, registry)) as db:
            ensure_samples(db)
            db.execute("INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (sample_id, scope.project, category, consent_id, timestamp(created), expires_at,
                        json.dumps(replay, ensure_ascii=False), payload))
    return {"status": "collected", "sample_id": sample_id, "category": category, "expires_at": expires_at}


def load_sample(project: Path, registry: Path, sample_id: str, category: str) -> ProjectSample:
    registry = registry_path(project, registry)
    contents = content_path(project, registry)
    scope_id = project_scope(project)
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        require_not_erased(grants, scope_id, sample_id=sample_id)
        if not contents.is_file():
            reject(ErrorCode.PERMISSION_DENIED, "Copie d'évolution introuvable.", reason="content_missing")
        with transaction(contents) as db:
            row = db.execute("SELECT project, category, consent_id, created_at, expires_at, manifest FROM samples WHERE sample_id = ?",
                             (sample_id,)).fetchone()
            if row is None:
                reject(ErrorCode.PERMISSION_DENIED, "Copie d'évolution introuvable.", reason="content_missing")
            stored_project, stored_category, consent_id, created_at, expires_at, encoded = row
            if stored_project != scope_id or stored_category != category:
                reject(ErrorCode.PERMISSION_DENIED, "Projet ou catégorie hors périmètre de la copie.",
                       reason="consent_scope_mismatch")
            scope = ReuseScope(stored_project, stored_category, consent_id, "project", False)
            manifest = json.loads(encoded)
            expires_at = timestamp(copy_deadline(created_at, expires_at))
            sample = ProjectSample(sample_id, scope, manifest, b"", created_at, expires_at)
            require_sample(grants, sample)
            payload = db.execute("SELECT payload FROM samples WHERE sample_id = ?", (sample_id,)).fetchone()[0]
            if digest(payload) != manifest[ARTIFACTS[category][1]]:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "La copie ne correspond plus à l'artefact validé.")
    return replace(sample, payload=payload)


def register_replay(project: Path, registry: Path, sample: ProjectSample, output: Path) -> str:
    registry = registry_path(project, registry)
    run_id = str(uuid4())
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        require_sample(grants, sample)
        output.mkdir(parents=True)
        with transaction(content_path(project, registry)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS project_replays (
                run_id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, location TEXT NOT NULL,
                running INTEGER NOT NULL, report_sha256 TEXT
            )""")
            db.execute("INSERT INTO project_replays VALUES (?, ?, ?, 1, NULL)",
                       (run_id, sample.sample_id, json.dumps(identity(output))))
    return run_id


def finish_replay(project: Path, registry: Path, sample: ProjectSample, run_id: str, result: dict | None) -> None:
    registry = registry_path(project, registry)
    refusal = None
    with transaction(registry) as grants, transaction(content_path(project, registry)) as db:
        grants.execute("BEGIN IMMEDIATE")
        checksum = None
        if result is not None:
            try:
                require_sample(grants, sample)
            except ProjectError as error:
                refusal = error
            else:
                location = db.execute("SELECT location FROM project_replays WHERE run_id = ?", (run_id,)).fetchone()[0]
                output = checked_output(project, json.loads(location))
                encoded = (json.dumps(result, indent=2) + "\n").encode("utf-8")
                with (output / "report.json").open("xb") as report:
                    report.write(encoded)
                checksum = digest(encoded)
        db.execute("UPDATE project_replays SET running = 0, report_sha256 = ? WHERE run_id = ?", (checksum, run_id))
        erasing = erasure_marker(grants, sample.scope.project, sample_id=sample.sample_id)
    if erasing is not None and erasing[1] == "pending":
        erase(project, registry, sample.sample_id)
    if refusal:
        raise refusal


def checked_output(project: Path, location: dict) -> Path:
    output = Path(location["path"])
    resolved = output.resolve(strict=True)
    if resolved != output or resolved.is_relative_to(project) or identity(resolved) != location:
        raise OSError("Le dossier de rejeu a changé.")
    return resolved


def request_erasure(project: Path, registry: Path, sample_id: str) -> dict:
    project = project.resolve(strict=True)
    registry = registry_path(project, registry)
    scope = project_scope(project)
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        if marker := erasure_marker(grants, scope, sample_id=sample_id):
            return {"request_id": marker[0], "status": marker[1]}
        contents = content_path(project, registry)
        if not contents.is_file():
            reject(ErrorCode.PERMISSION_DENIED, "Copie d'évolution introuvable.", reason="content_missing")
        with transaction(contents) as db:
            row = db.execute("SELECT manifest FROM samples WHERE project = ? AND sample_id = ?", (scope, sample_id)).fetchone()
            if row is None:
                reject(ErrorCode.PERMISSION_DENIED, "Copie d'évolution introuvable.", reason="content_missing")
            proposal = json.loads(row[0])["proposal_sha256"]
            related = db.execute("""SELECT sample_id, json_extract(manifest, '$.source_id') FROM samples
                                    WHERE project = ? AND json_extract(manifest, '$.proposal_sha256') = ?""",
                                 (scope, proposal)).fetchall()
        request_id = str(uuid4())
        requested_at = timestamp(datetime.now(timezone.utc))
        grants.execute("""CREATE TABLE IF NOT EXISTS project_erasures (
            sample_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, project TEXT NOT NULL, source_id TEXT,
            requested_at TEXT NOT NULL, state TEXT NOT NULL, reason TEXT
        )""")
        grants.executemany("INSERT INTO project_erasures VALUES (?, ?, ?, ?, ?, 'pending', NULL)",
                           [(copy_id, request_id, scope, source_id, requested_at) for copy_id, source_id in related])
        try:
            sync_erasures(project, registry, grants, scope)
        except (OSError, RuntimeError, sqlite3.Error, ValueError, KeyError):
            grants.execute("UPDATE project_erasures SET reason = 'key_unavailable' WHERE request_id = ?", (request_id,))
    return {"request_id": request_id, "status": "pending", "blocked_copies": len(related)}


def replay_report(project: Path, location: dict, checksum: str | None) -> tuple[Path, bytes] | None:
    report = checked_output(project, location) / "report.json"
    try:
        info = report.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError("Le rapport de rejeu ne correspond plus à l'inventaire.")
    content = report.read_bytes()
    if checksum != digest(content):
        raise OSError("Le rapport de rejeu ne correspond plus à l'inventaire.")
    return report, content


def remove_replay_report(project: Path, location: dict, checksum: str | None) -> bool:
    found = replay_report(project, location, checksum)
    if found is None:
        return False
    report, _ = found
    report.unlink()
    if report.exists():
        raise OSError("Le rapport de rejeu existe encore après suppression.")
    return True


def erase(project: Path, registry: Path, sample_id: str) -> dict:
    project = project.resolve(strict=True)
    registry = registry_path(project, registry)
    result = finish_erasure(project, registry, sample_id)
    decision = result["status"]
    if decision == "erased" and "copies_erased" not in result:
        decision = "confirmed"
    audit_decision(registry, action="evolution_erase", risk="R3", actor="runtime",
                   decision=decision, reason=result.get("reason"))
    return result


def finish_erasure(project: Path, registry: Path, sample_id: str) -> dict:
    request = request_erasure(project, registry, sample_id)
    if request["status"] == "erased":
        return request
    request_id = request["request_id"]
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        scope = project_scope(project)
        marker = erasure_marker(grants, scope, sample_id=sample_id)
        if marker[1] == "erased":
            return {"request_id": request_id, "status": "erased"}
        ids = [row[0] for row in grants.execute("SELECT sample_id FROM project_erasures WHERE request_id = ? AND project = ?",
                                               (request_id, scope))]

        def pending(reason: str) -> dict:
            grants.execute("UPDATE project_erasures SET reason = ? WHERE request_id = ?", (reason, request_id))
            return {"request_id": request_id, "status": "pending", "reason": reason}

        contents = content_path(project, registry)
        if not contents.is_file():
            return pending("copy_unreachable")
        try:
            with transaction(contents) as db:
                db.execute("PRAGMA secure_delete = ON")
                replay_table = table_exists(db, "project_replays")
                restored_table = table_exists(db, "restored_reports")
                replays = []
                if replay_table:
                    for copy_id in ids:
                        replays.extend(db.execute("SELECT location, running, report_sha256 FROM project_replays WHERE sample_id = ?",
                                                  (copy_id,)).fetchall())
                if any(running for _, running, _ in replays):
                    return pending("replay_in_progress")
                reports_removed = sum(remove_replay_report(project, json.loads(location), checksum)
                                      for location, _, checksum in replays)
                db.executemany("DELETE FROM samples WHERE sample_id = ?", [(copy_id,) for copy_id in ids])
                if replay_table:
                    db.executemany("DELETE FROM project_replays WHERE sample_id = ?", [(copy_id,) for copy_id in ids])
                if restored_table:
                    cursor = db.executemany("DELETE FROM restored_reports WHERE sample_id = ?", [(copy_id,) for copy_id in ids])
                    reports_removed += cursor.rowcount
                db.commit()
                if db.execute("PRAGMA journal_mode").fetchone()[0] == "wal" and db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                    return pending("copy_unreachable")
                if any(db.execute("SELECT 1 FROM samples WHERE sample_id = ?", (copy_id,)).fetchone() for copy_id in ids):
                    return pending("verification_incomplete")
                if replay_table and any(db.execute("SELECT 1 FROM project_replays WHERE sample_id = ?", (copy_id,)).fetchone()
                                        for copy_id in ids):
                    return pending("verification_incomplete")
                if restored_table and any(db.execute("SELECT 1 FROM restored_reports WHERE sample_id = ?", (copy_id,)).fetchone()
                                           for copy_id in ids):
                    return pending("verification_incomplete")
        except (OSError, ProjectError, sqlite3.Error, json.JSONDecodeError):
            return pending("copy_unreachable")
        try:
            sync_erasures(project, registry, grants, scope)
        except (OSError, RuntimeError, sqlite3.Error, ValueError, KeyError):
            return pending("key_unavailable")
        grants.execute("UPDATE project_erasures SET state = 'erased', reason = NULL WHERE request_id = ?", (request_id,))
    return {"request_id": request_id, "status": "erased", "copies_erased": len(ids), "reports_removed": reports_removed}


def expire_copies(project: Path, registry: Path, *, now: datetime | None = None) -> list[dict]:
    """Réutilise la barrière d'effacement et son traitement des rapports et clés."""
    project = project.resolve(strict=True)
    registry = registry_path(project, registry, require_existing=False)
    contents = content_path(project, registry)
    if not registry.is_file() or not contents.is_file():
        return []
    moment = now or datetime.now(timezone.utc)
    policy = load_policy()
    with transaction(contents) as db:
        if not table_exists(db, "samples"):
            return []
        scope = project_scope(project)
        samples = db.execute("SELECT sample_id, created_at, expires_at FROM samples WHERE project = ?", (scope,))
        expired = [sample for sample, created, expires in samples if moment >= copy_deadline(created, expires, policy=policy)]
    requests = {}
    for sample in expired:
        result = erase(project, registry, sample)
        requests.setdefault(result["request_id"], result)
    return list(requests.values())
