"""Coffre local et tête authentifiée du registre d'effacement."""

from base64 import b64decode, b64encode
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from contracts.akasha_contracts.errors import ErrorCode

from .experience import transaction
from .project_common import reject


def encode(data: bytes) -> str:
    return b64encode(data).decode("ascii")


def decode(data: str) -> bytes:
    return b64decode(data, validate=True)


def pack(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def crypto(action: str, **fields) -> dict:
    powershell = shutil.which("pwsh.exe")
    if powershell is None:
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "PowerShell 7 est requis pour le coffre Windows.")
    command = Path(__file__).with_name("project_crypto.ps1")
    try:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(command), "-Action", action],
                                input=pack(fields), capture_output=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        reject(ErrorCode.TIMEOUT_EXCEEDED, "Le coffre ne répond pas.", reason="key_unavailable")
    if result.returncode:
        reject(ErrorCode.PERMISSION_DENIED, "Le coffre ou l'objet chiffré n'est pas vérifiable.", reason="key_unavailable")
    return json.loads(result.stdout)


def table_exists(db, table: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def ledger(db, scope: str) -> list[list[str | None]]:
    if not table_exists(db, "project_erasures"):
        return []
    return [list(row) for row in db.execute("""SELECT sample_id, source_id, request_id, requested_at
                                 FROM project_erasures WHERE project = ? ORDER BY sample_id""", (scope,))]


def vault_path(project: Path, registry: Path) -> Path:
    nominal = registry.with_name(registry.name + ".backup-vault.sqlite")
    path = nominal.resolve()
    if path != nominal or path.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "Emplacement de coffre invalide.", reason="ledger_unverified")
    return path


def configured_vault(db, scope: str) -> str | None:
    if not table_exists(db, "project_backup_config"):
        return None
    row = db.execute("SELECT vault_id FROM project_backup_config WHERE project = ?", (scope,)).fetchone()
    return row[0] if row else None


def initialize_vault(grants, vault, scope: str) -> str:
    vault.execute("CREATE TABLE IF NOT EXISTS backup_heads (project TEXT PRIMARY KEY, seal TEXT NOT NULL)")
    vault.execute("""CREATE TABLE IF NOT EXISTS backup_keys (
        project TEXT NOT NULL, backup_id TEXT NOT NULL, item_id TEXT NOT NULL,
        source_id TEXT, wrapped TEXT NOT NULL, PRIMARY KEY (backup_id, item_id)
    )""")
    grants.execute("CREATE TABLE IF NOT EXISTS project_backup_config (project TEXT PRIMARY KEY, vault_id TEXT NOT NULL)")
    vault_id = str(uuid4())
    write_head(vault, scope, {"vault_id": vault_id, "project": scope, "generation": 0, "markers": ledger(grants, scope)})
    grants.execute("INSERT INTO project_backup_config VALUES (?, ?)", (scope, vault_id))
    return vault_id


def write_head(vault, scope: str, head: dict) -> None:
    sealed = crypto("seal", data=encode(pack(head)))["data"]
    vault.execute("INSERT INTO backup_heads VALUES (?, ?) ON CONFLICT (project) DO UPDATE SET seal = excluded.seal",
                  (scope, sealed))


def read_head(vault, scope: str, vault_id: str) -> dict:
    if not table_exists(vault, "backup_heads"):
        reject(ErrorCode.PERMISSION_DENIED, "Tête du registre d'effacement introuvable.", reason="ledger_unverified")
    row = vault.execute("SELECT seal FROM backup_heads WHERE project = ?", (scope,)).fetchone()
    if row is None:
        reject(ErrorCode.PERMISSION_DENIED, "Tête du registre d'effacement introuvable.", reason="ledger_unverified")
    head = json.loads(decode(crypto("unseal", data=row[0])["data"]))
    if head["project"] != scope or head["vault_id"] != vault_id:
        reject(ErrorCode.PERMISSION_DENIED, "Tête du registre d'effacement incompatible.", reason="ledger_unverified")
    return head


def verify_head(grants, vault, scope: str, vault_id: str) -> dict:
    head = read_head(vault, scope, vault_id)
    if head["markers"] != ledger(grants, scope):
        reject(ErrorCode.PERMISSION_DENIED, "Le registre d'effacement courant ne correspond pas au coffre.",
               reason="ledger_unverified")
    return head


def sync_erasures(project: Path, registry: Path, grants, scope: str) -> None:
    vault_id = configured_vault(grants, scope)
    if vault_id is None:
        return
    path = vault_path(project, registry)
    if not path.is_file():
        reject(ErrorCode.PERMISSION_DENIED, "Coffre d'effacement indisponible.", reason="key_unavailable")
    with transaction(path) as vault:
        head = read_head(vault, scope, vault_id)
        current = ledger(grants, scope)
        if not {tuple(marker) for marker in head["markers"]} <= {tuple(marker) for marker in current}:
            reject(ErrorCode.PERMISSION_DENIED, "Le registre d'effacement est antérieur à sa tête.", reason="ledger_unverified")
        vault.execute("PRAGMA secure_delete = ON")
        vault.executemany("DELETE FROM backup_keys WHERE project = ? AND (item_id = ? OR source_id = ?)",
                          [(scope, sample_id, source_id) for sample_id, source_id, _, _ in current])
        if current != head["markers"]:
            write_head(vault, scope, {**head, "generation": head["generation"] + 1, "markers": current})
        vault.commit()
        if vault.execute("PRAGMA journal_mode").fetchone()[0] == "wal" and vault.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            reject(ErrorCode.PERMISSION_DENIED, "La purge des clés du coffre reste en attente.", reason="key_unavailable")
        if any(vault.execute("SELECT 1 FROM backup_keys WHERE project = ? AND (item_id = ? OR source_id = ?)",
                             (scope, sample_id, source_id)).fetchone() for sample_id, source_id, _, _ in current):
            reject(ErrorCode.PERMISSION_DENIED, "La purge des clés du coffre reste en attente.", reason="key_unavailable")
