"""Limite disque du journal local et éviction des artefacts orphelins."""

import os

from .memory_store import MemoryRefusal


def configured_limit() -> int | None:
    value = os.environ.get("AKASHA_MEMORY_DISK_BYTES")
    if value is None:
        return None
    limit = int(value)
    if limit <= 0:
        raise ValueError("Le plafond disque doit être strictement positif.")
    return limit


def used_bytes(memory) -> int:
    suffixes = (".memory-control.sqlite", ".memory-vault.sqlite", ".backups", ".registry", ".scratch")
    paths = [memory.path, *(memory.path.with_name(memory.path.name + suffix) for suffix in suffixes)]
    size = 0
    for path in paths:
        if path.resolve() != path:
            raise MemoryRefusal("storage_unverified", "Emplacement de stockage non vérifiable.")
        if path.is_file():
            size += path.stat().st_size
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.resolve() != file:
                    raise MemoryRefusal("storage_unverified", "Emplacement de stockage non vérifiable.")
                if file.is_file():
                    size += file.stat().st_size
    return size


def enforce(memory, *, limit: int | None = None) -> dict | None:
    from .memory_backup import open_vault, vault_id

    configured = configured_limit() if limit is None else limit
    if configured is None:
        return None
    count = 0
    while (size := used_bytes(memory)) > configured:
        with memory.access() as (control, db):
            protected = set()
            if vault_id(control) is not None:
                with open_vault(memory, control) as (vault, _, _):
                    protected = {row[0] for row in vault.execute("SELECT DISTINCT parent FROM backup_lineage")}
            choices = db.execute("""SELECT id FROM memory_items AS object WHERE kind = 'artifact'
                AND NOT EXISTS (SELECT 1 FROM memory_lineage WHERE parent = object.id)
                ORDER BY created_at, id""").fetchall()
            candidate = next((item[0] for item in choices if item[0] not in protected), None)
            if candidate is None:
                return {"status": "over_budget", "bytes": size, "limit": configured, "evicted": count}
            memory.mark(control, db, candidate, "disk_budget", memory.clock())
        memory.audit_erasure("disk_budget")
        memory.finish_erasures()
        with memory.access() as (_, db):
            db.commit()
            db.execute("VACUUM")
        count += 1
    return {"status": "within_budget", "bytes": size, "limit": configured, "evicted": count}
