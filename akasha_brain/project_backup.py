"""Sauvegarde Windows chiffrée et restauration filtrée du stockage d'évolution."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from contracts.akasha_contracts.errors import ErrorCode
from contracts.akasha_contracts.validate import validate

from .evolution_consent import ReuseScope, check_reuse, instant, timestamp
from .experience import transaction
from .project_backup_vault import (
    configured_vault, crypto, decode, encode, initialize_vault, pack, table_exists, vault_path, verify_head,
)
from .project_common import ProjectError, digest, project_scope, reject
from .project_evolution import ARTIFACTS, content_path, ensure_samples, erasure_marker, registry_path, replay_report

FORMAT = "akasha-project-backup/1"
SAMPLE_COLUMNS = ("sample_id", "project", "category", "consent_id", "created_at", "expires_at", "manifest")


def grant_backup(project: Path, registry: Path, categories: list[str], expires_at: str | None = None) -> dict:
    project = project.resolve(strict=True)
    registry = registry.resolve()
    if registry.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "Le registre de sauvegarde doit être hors du projet.")
    now = datetime.now(timezone.utc)
    expires = instant(expires_at) if expires_at is not None else None
    if expires is not None and expires <= now:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'échéance doit suivre l'accord.")
    document = {"version": "1.0.0", "consent_id": str(uuid4()), "project": project_scope(project),
                "categories": categories, "purpose": "local_backup", "granted_at": timestamp(now),
                "expires_at": timestamp(expires) if expires is not None else None, "status": "active"}
    if errors := validate(document, "BackupConsent"):
        raise ProjectError(errors[0])
    if any(category not in ARTIFACTS for category in categories):
        reject(ErrorCode.PERMISSION_DENIED, "Catégorie de sauvegarde exclue.")
    with transaction(registry) as db:
        db.execute("CREATE TABLE IF NOT EXISTS project_backup_consents (consent_id TEXT PRIMARY KEY, document TEXT NOT NULL)")
        db.execute("INSERT INTO project_backup_consents VALUES (?, ?)", (document["consent_id"], pack(document)))
    return document


def backup_consent(db, scope: str, consent_id: str | None, now: datetime) -> dict:
    row = (db.execute("SELECT document FROM project_backup_consents WHERE consent_id = ?", (consent_id,)).fetchone()
           if consent_id is not None and table_exists(db, "project_backup_consents") else None)
    if row is None:
        reject(ErrorCode.APPROVAL_REQUIRED, "Un accord distinct de sauvegarde est requis.", reason="backup_consent_missing")
    document = json.loads(row[0])
    if errors := validate(document, "BackupConsent"):
        raise ProjectError(errors[0])
    if document["project"] != scope or document["consent_id"] != consent_id:
        reject(ErrorCode.PERMISSION_DENIED, "Accord de sauvegarde hors projet.", reason="backup_consent_scope_mismatch")
    expires = document["expires_at"]
    if document["status"] != "active" or now < instant(document["granted_at"]) or (expires and now >= instant(expires)):
        reject(ErrorCode.PERMISSION_DENIED, "Accord de sauvegarde inactif.", reason="backup_consent_inactive")
    return document


def revoke_backup(project: Path, registry: Path, consent_id: str) -> dict:
    project = project.resolve(strict=True)
    with transaction(registry_path(project, registry)) as db:
        db.execute("BEGIN IMMEDIATE")
        row = (db.execute("SELECT document FROM project_backup_consents WHERE consent_id = ?", (consent_id,)).fetchone()
               if table_exists(db, "project_backup_consents") else None)
        if row is None:
            reject(ErrorCode.APPROVAL_REQUIRED, "Accord de sauvegarde introuvable.", reason="backup_consent_missing")
        document = json.loads(row[0])
        if document["project"] != project_scope(project):
            reject(ErrorCode.PERMISSION_DENIED, "Accord de sauvegarde hors projet.", reason="backup_consent_scope_mismatch")
        document["status"] = "revoked"
        db.execute("UPDATE project_backup_consents SET document = ? WHERE consent_id = ?", (pack(document), consent_id))
    return document


def associated_data(scope: str, backup_id: str, item_id: str) -> str:
    return encode(pack([FORMAT, scope, backup_id, item_id]))


def encrypt(vault, scope: str, backup_id: str, item_id: str, source_id: str | None, value) -> dict:
    encrypted = crypto("encrypt", data=encode(pack(value)), aad=associated_data(scope, backup_id, item_id))
    wrapped = encrypted.pop("key")
    vault.execute("INSERT INTO backup_keys VALUES (?, ?, ?, ?, ?)", (scope, backup_id, item_id, source_id, wrapped))
    return encrypted


def decrypt(vault, scope: str, backup_id: str, item_id: str, encrypted: dict):
    row = vault.execute("SELECT wrapped FROM backup_keys WHERE project = ? AND backup_id = ? AND item_id = ?",
                        (scope, backup_id, item_id)).fetchone()
    if row is None:
        reject(ErrorCode.PERMISSION_DENIED, "Clé d'objet introuvable.", reason="key_unavailable")
    return json.loads(decode(crypto("decrypt", **encrypted, key=row[0], aad=associated_data(scope, backup_id, item_id))["data"]))


def publish(output: Path, package: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=output.parent, prefix=".akasha-backup-", delete=False) as file:
            temporary = Path(file.name)
            file.write(pack(package))
        temporary.rename(output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def collect_reports(db, project: Path, sample_id: str) -> dict[str, str]:
    reports = {}
    if table_exists(db, "project_replays"):
        for run_id, location, checksum in db.execute("""SELECT run_id, location, report_sha256 FROM project_replays
                            WHERE sample_id = ? AND running = 0 AND report_sha256 IS NOT NULL""", (sample_id,)):
            found = replay_report(project, json.loads(location), checksum)
            if found is None:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Rapport dérivé inaccessible.", reason="copy_unreachable")
            reports[run_id] = encode(found[1])
    if table_exists(db, "restored_reports"):
        for run_id, payload in db.execute("SELECT run_id, payload FROM restored_reports WHERE sample_id = ?", (sample_id,)):
            reports[run_id] = encode(payload)
    return reports


def backup(project: Path, registry: Path, output: Path, consent_id: str | None) -> dict:
    project = project.resolve(strict=True)
    registry = registry_path(project, registry)
    scope = project_scope(project)
    output = output.resolve()
    if output.is_relative_to(project) or output.exists():
        reject(ErrorCode.PERMISSION_DENIED, "Choisir un nouveau fichier de sauvegarde hors du projet.")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)
    backup_id = str(uuid4())
    items = []
    objects = {}
    reports_count = 0
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        consent = backup_consent(grants, scope, consent_id, now)
        contents = content_path(project, registry)
        if not contents.is_file():
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Aucune copie d'évolution à sauvegarder.")
        vault_file = vault_path(project, registry)
        vault_id = configured_vault(grants, scope)
        if vault_id is not None and not vault_file.is_file():
            reject(ErrorCode.PERMISSION_DENIED, "Le coffre courant est indisponible.", reason="ledger_unverified")
        with transaction(vault_file) as vault, transaction(contents) as db:
            if vault_id is None:
                if table_exists(vault, "backup_heads") and vault.execute("SELECT 1 FROM backup_heads WHERE project = ?", (scope,)).fetchone():
                    reject(ErrorCode.PERMISSION_DENIED, "Le registre courant est incomplet.", reason="ledger_unverified")
                vault_id = initialize_vault(grants, vault, scope)
            head = verify_head(grants, vault, scope, vault_id)
            for row in db.execute(f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM samples WHERE project = ? ORDER BY sample_id", (scope,)):
                sample = dict(zip(SAMPLE_COLUMNS, row))
                category = sample["category"]
                if category not in consent["categories"] or now >= instant(sample["expires_at"]):
                    continue
                sample_id = sample["sample_id"]
                manifest = json.loads(sample["manifest"])
                source_id = manifest.get("source_id")
                scope_entry = ReuseScope(scope, category, sample["consent_id"], "project", False)
                if erasure_marker(grants, scope, sample_id=sample_id, source_id=source_id) or check_reuse(grants, (scope_entry,)):
                    continue
                metadata = {"sample_id": sample_id, "source_id": source_id, "category": category,
                            "consent_id": sample["consent_id"],
                            "expires_at": timestamp(min(expires_at, instant(sample["expires_at"])))}
                payload = db.execute("SELECT payload FROM samples WHERE sample_id = ?", (sample_id,)).fetchone()[0]
                if digest(payload) != manifest[ARTIFACTS[category][1]]:
                    reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Empreinte de copie invalide.")
                reports = collect_reports(db, project, sample_id)
                objects[sample_id] = encrypt(vault, scope, backup_id, sample_id, source_id,
                                             {"sample": sample, "payload": encode(payload), "reports": reports})
                items.append(metadata)
                reports_count += len(reports)
            if not items:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Aucune copie dans le périmètre autorisé.")
            index = {"vault_id": vault_id, "generation": head["generation"], "expires_at": timestamp(expires_at),
                     "backup_consent_id": consent_id, "items": items}
            envelope = {"format": FORMAT, "backup_id": backup_id, "objects": objects,
                        "index": encrypt(vault, scope, backup_id, "index", None, index)}
            publication = datetime.now(timezone.utc)
            backup_consent(grants, scope, consent_id, publication)
            if any(publication >= instant(item["expires_at"]) for item in items):
                reject(ErrorCode.PERMISSION_DENIED, "Une copie a expiré pendant la sauvegarde.", reason="content_expired")
            publish(output, envelope)
    return {"status": "backed_up", "backup_id": backup_id, "copies": len(items), "reports": reports_count,
            "expires_at": timestamp(expires_at), "cipher": "AES-256-GCM", "key_protection": "DPAPI CurrentUser"}


def restore_item(value: dict, item: dict, scope: str) -> tuple[dict, bytes, dict[str, bytes]]:
    sample = value["sample"]
    manifest = json.loads(sample["manifest"])
    if (set(sample) != set(SAMPLE_COLUMNS) or sample["project"] != scope
            or any(sample[key] != item[key] for key in ("sample_id", "category", "consent_id"))
            or manifest.get("source_id") != item["source_id"]):
        reject(ErrorCode.PERMISSION_DENIED, "Filiation de la copie incohérente.", reason="lineage_invalid")
    payload = decode(value["payload"])
    if digest(payload) != manifest[ARTIFACTS[sample["category"]][1]]:
        reject(ErrorCode.PERMISSION_DENIED, "Empreinte de copie invalide.", reason="lineage_invalid")
    sample["expires_at"] = timestamp(min(instant(sample["expires_at"]), instant(item["expires_at"])))
    reports = {str(UUID(run_id)): decode(data) for run_id, data in value["reports"].items()}
    if any(json.loads(data).get("sample_id") != sample["sample_id"] for data in reports.values()):
        reject(ErrorCode.PERMISSION_DENIED, "Rapport dérivé sans filiation valide.", reason="lineage_invalid")
    return sample, payload, reports


def restore(project: Path, registry: Path, archive: Path) -> dict:
    project = project.resolve(strict=True)
    if not registry.is_file():
        reject(ErrorCode.PERMISSION_DENIED, "Le registre d'effacement courant est requis.", reason="ledger_unverified")
    registry = registry_path(project, registry)
    scope = project_scope(project)
    vault_file = vault_path(project, registry)
    with transaction(registry) as grants:
        grants.execute("BEGIN IMMEDIATE")
        vault_id = configured_vault(grants, scope)
        if vault_id is None or not vault_file.is_file():
            reject(ErrorCode.PERMISSION_DENIED, "Le coffre et le registre d'effacement courants sont requis.", reason="ledger_unverified")
        with transaction(vault_file) as vault:
            head = verify_head(grants, vault, scope, vault_id)
            envelope = json.loads(archive.read_bytes())
            backup_id = str(UUID(envelope["backup_id"]))
            if envelope["format"] != FORMAT:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Format de sauvegarde inconnu.")
            index = decrypt(vault, scope, backup_id, "index", envelope["index"])
            if index["vault_id"] != vault_id or index["generation"] > head["generation"]:
                reject(ErrorCode.PERMISSION_DENIED, "Le registre est antérieur ou incompatible.", reason="ledger_unverified")
            now = datetime.now(timezone.utc)
            if now >= instant(index["expires_at"]):
                reject(ErrorCode.PERMISSION_DENIED, "Sauvegarde expirée.", reason="backup_expired")
            consent = backup_consent(grants, scope, index["backup_consent_id"], now)
            item_ids = [item["sample_id"] for item in index["items"]]
            if len(set(item_ids)) != len(item_ids) or set(item_ids) != set(envelope["objects"]):
                reject(ErrorCode.PERMISSION_DENIED, "L'inventaire de sauvegarde est incohérent.", reason="lineage_invalid")

            staged = []
            skipped_erased = 0
            skipped_inactive = 0
            for item in index["items"]:
                sample_id = item["sample_id"]
                if erasure_marker(grants, scope, sample_id=sample_id, source_id=item["source_id"]):
                    skipped_erased += 1
                    continue
                use = ReuseScope(scope, item["category"], item["consent_id"], "project", False)
                if (item["category"] not in consent["categories"] or now >= instant(item["expires_at"])
                        or check_reuse(grants, (use,))):
                    skipped_inactive += 1
                    continue
                value = decrypt(vault, scope, backup_id, sample_id, envelope["objects"][sample_id])
                staged.append(restore_item(value, item, scope))
            verify_head(grants, vault, scope, vault_id)
            publication = datetime.now(timezone.utc)
            backup_consent(grants, scope, index["backup_consent_id"], publication)
            if publication >= instant(index["expires_at"]) or any(publication >= instant(sample["expires_at"])
                                                                 for sample, _, _ in staged):
                reject(ErrorCode.PERMISSION_DENIED, "Une échéance a été atteinte pendant la restauration.", reason="content_expired")

        copies = 0
        reports_count = 0
        if staged:
            with transaction(content_path(project, registry)) as db:
                db.execute("BEGIN IMMEDIATE")
                ensure_samples(db)
                db.execute("""CREATE TABLE IF NOT EXISTS restored_reports (
                    run_id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, payload BLOB NOT NULL
                )""")
                replay_table = table_exists(db, "project_replays")
                for sample, payload, reports in staged:
                    sample_id = sample["sample_id"]
                    copied = db.execute("INSERT OR IGNORE INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                        (*[sample[key] for key in SAMPLE_COLUMNS], payload)).rowcount
                    copies += copied
                    if not copied:
                        continue
                    for run_id, data in reports.items():
                        if replay_table and db.execute("SELECT 1 FROM project_replays WHERE run_id = ?", (run_id,)).fetchone():
                            continue
                        reports_count += db.execute("INSERT OR IGNORE INTO restored_reports VALUES (?, ?, ?)",
                                                    (run_id, sample_id, data)).rowcount
    return {"status": "restored", "backup_id": backup_id, "copies_restored": copies,
            "reports_restored": reports_count, "skipped_erased": skipped_erased, "skipped_inactive": skipped_inactive}
