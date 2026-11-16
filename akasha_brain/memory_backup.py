"""Sauvegardes locales chiffrées des mémoires techniques, sans clés exportées."""

from argparse import ArgumentParser
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from time import sleep
from uuid import uuid4

from .memory import NOTES_SCOPE, canonical_id
from .memory_budget import configured_limit, enforce, used_bytes
from .memory_store import MemoryRefusal, MemoryStore, connect, expiration, related, row_for, stamp
from .project_audit import record
from .project_backup import publish
from .project_backup_vault import crypto, decode, encode, pack, table_exists
from .project_common import ProjectError, digest
from .retention import deadline, load_policy

FORMAT = "Akasha.MemoryBackup.v3"
COLUMNS = ("id", "kind", "scope", "payload", "created_at", "expires_at", "retention")


def vault_path(memory: MemoryStore) -> Path:
    return memory.path.with_name(f"{memory.path.name}.memory-vault.sqlite")


def archive_path(memory: MemoryStore, backup_id: str) -> Path:
    name = f"{canonical_id(backup_id)}.backup"
    path = memory.path.with_name(f"{memory.path.name}.backups") / name
    if path.resolve() != path:
        raise MemoryRefusal("archive_unverified", "Emplacement de sauvegarde invérifiable.")
    return path


def seen_markers(control) -> list[list[str | int]]:
    return [list(row) for row in control.execute(
        "SELECT id, requested_at, reason, is_trace FROM memory_erasures ORDER BY id")]


def vault_id(control) -> str | None:
    if not table_exists(control, "memory_backup_config"):
        return None
    row = control.execute("SELECT id FROM memory_backup_config WHERE singleton = 1").fetchone()
    if row is None:
        raise MemoryRefusal("ledger_unverified", "Configuration du coffre incomplète.")
    return row[0]


def seal_head(vault, identity: str, markers: list[list[str | int]]) -> None:
    head = encode(pack({"format": FORMAT, "vault": identity, "markers": markers}))
    vault.execute("INSERT OR REPLACE INTO ledger_head VALUES (1, ?)", (crypto("seal", data=head)["data"],))


def head_for(vault, identity: str) -> list[list[str | int]]:
    row = vault.execute("SELECT seal FROM ledger_head WHERE singleton = 1").fetchone()
    if row is None:
        raise MemoryRefusal("ledger_unverified", "Tête du registre d'effacement manquante.")
    head = json.loads(decode(crypto("unseal", data=row[0])["data"]))
    if head["format"] != FORMAT or head["vault"] != identity:
        raise MemoryRefusal("ledger_unverified", "Tête de registre incompatible.")
    return head["markers"]


@contextmanager
def open_vault(memory, control, *, setup=False):
    identity = vault_id(control)
    path = vault_path(memory)
    if path.resolve() != path:
        raise MemoryRefusal("ledger_unverified", "Emplacement du coffre invalide.")
    if identity is None:
        if not setup or path.exists():
            raise MemoryRefusal("ledger_unverified", "Coffre non configuré ou sans registre associé.")
        identity = str(uuid4())
        with connect(path, create=True) as vault:
            vault.execute("CREATE TABLE ledger_head (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), seal TEXT)")
            vault.execute("""CREATE TABLE archives (
                id TEXT PRIMARY KEY, issued TEXT NOT NULL, expires TEXT NOT NULL, envelope_digest TEXT NOT NULL
            )""")
            vault.execute("""CREATE TABLE keys (
                backup TEXT NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
                item TEXT NOT NULL, wrapped TEXT NOT NULL, is_trace INTEGER NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL, retention TEXT NOT NULL,
                PRIMARY KEY (backup, item)
            )""")
            vault.execute("""CREATE TABLE backup_lineage (
                backup TEXT NOT NULL, child TEXT NOT NULL, parent TEXT NOT NULL,
                PRIMARY KEY (backup, child, parent), FOREIGN KEY (backup, child) REFERENCES keys(backup, item) ON DELETE CASCADE
            )""")
            vault.execute("CREATE INDEX backup_children ON backup_lineage (parent)")
            seal_head(vault, identity, seen_markers(control))
        control.execute("CREATE TABLE memory_backup_config (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), id TEXT)")
        control.execute("INSERT INTO memory_backup_config VALUES (1, ?)", (identity,))
    if not path.is_file():
        raise MemoryRefusal("ledger_unverified", "Coffre de sauvegarde introuvable.")
    with connect(path) as vault:
        yield vault, identity, head_for(vault, identity)


def archived_kind(memory, control, item_id):
    if vault_id(control) is None:
        return None
    with open_vault(memory, control) as (vault, _, previous):
        if previous != seen_markers(control):
            raise MemoryRefusal("ledger_unverified", "Le registre courant diffère du coffre.")
        row = vault.execute("SELECT MAX(is_trace) FROM keys WHERE item = ?", (item_id,)).fetchone()
        return row[0]


def mark_archived_expiry(memory, control, now, policy) -> int:
    if vault_id(control) is None:
        return 0
    with open_vault(memory, control) as (vault, _, previous):
        if not {tuple(item) for item in previous} <= {tuple(item) for item in seen_markers(control)}:
            raise MemoryRefusal("ledger_unverified", "Le registre a perdu des marqueurs d'effacement.")
        changed = 0
        for row in vault.execute("SELECT DISTINCT item, is_trace, created_at, expires_at, retention FROM keys"):
            if expiration(row, policy) <= now:
                changed += control.execute("INSERT OR IGNORE INTO memory_erasures VALUES (?, ?, 'expired', 0, ?)",
                                           (row["item"], stamp(now), row["is_trace"])).rowcount
        return changed


def include_backup_descendants(memory, control, db, ids: list[str]) -> None:
    if not ids or vault_id(control) is None:
        return
    with open_vault(memory, control) as (vault, _, previous):
        markers = seen_markers(control)
        if not {tuple(item) for item in previous} <= {tuple(item) for item in markers}:
            raise MemoryRefusal("ledger_unverified", "Le registre a perdu des marqueurs d'effacement.")
        visited = set(ids)
        pending = ids.copy()
        now = stamp(memory.clock())
        while pending:
            item_id = pending.pop()
            children = set(related(db, item_id, ancestors=False))
            children.update(row[0] for row in vault.execute("SELECT child FROM backup_lineage WHERE parent = ?", (item_id,)))
            for child in children - visited:
                live = row_for(db, child)
                archived = vault.execute("SELECT MAX(is_trace) FROM keys WHERE item = ?", (child,)).fetchone()
                is_trace = int(bool(archived[0] or (live and live["kind"] == "trace")))
                control.execute("INSERT OR IGNORE INTO memory_erasures VALUES (?, ?, 'derived', 0, ?)",
                                (child, now, is_trace))
                visited.add(child)
                pending.append(child)


def purge_keys(memory, control, ids: list[str]) -> None:
    """Supprime toutes les clés touchées, puis vérifie le coffre et ses journaux."""
    if vault_id(control) is None:
        if vault_path(memory).exists() or memory.path.with_name(f"{memory.path.name}.backups").exists():
            raise MemoryRefusal("ledger_unverified", "Le coffre présent n'est pas associé au registre courant.")
        return
    with open_vault(memory, control) as (vault, identity, previous):
        markers = seen_markers(control)
        if not {tuple(item) for item in previous} <= {tuple(item) for item in markers}:
            raise MemoryRefusal("ledger_unverified", "Le registre a perdu des marqueurs d'effacement.")
        wrapped = [row[0].encode("ascii") for item in ids
                   for row in vault.execute("SELECT wrapped FROM keys WHERE item = ?", (item,))]
        vault.executemany("DELETE FROM keys WHERE item = ?", ((item,) for item in ids))
        if markers != previous:
            seal_head(vault, identity, markers)
        vault.commit()
        vault.execute("BEGIN IMMEDIATE")
        path = vault_path(memory)
        disk = path.read_bytes() if wrapped else b""
        if (any(key in disk for key in wrapped)
                or any(vault.execute("SELECT 1 FROM keys WHERE item = ?", (item,)).fetchone() for item in ids)
                or any(vault.execute("SELECT 1 FROM backup_lineage WHERE parent = ?", (item,)).fetchone() for item in ids)
                or any(path.with_name(f"{path.name}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm"))):
            raise MemoryRefusal("erasure_pending", "L'effacement des clés ou de leurs journaux reste à vérifier.")


def aad(identity: str, backup_id: str, item_id: str) -> str:
    return encode(pack([FORMAT, identity, backup_id, item_id]))


def rotate(memory, vault, now, policy) -> None:
    for row in vault.execute("SELECT id, issued, expires FROM archives").fetchall():
        limit = deadline(datetime.fromisoformat(row["issued"]), "backup",
                         parent_deadlines=(datetime.fromisoformat(row["expires"]),), policy=policy)
        if now >= limit:
            path = archive_path(memory, row["id"])
            path.unlink(missing_ok=True)
            if path.exists():
                raise MemoryRefusal("rotation_pending", "Une génération expirée reste présente.")
            vault.execute("DELETE FROM archives WHERE id = ?", (row["id"],))


def todays_archive(memory, vault, now):
    for row in vault.execute("SELECT id FROM archives WHERE substr(issued, 1, 10) = ?", (stamp(now)[:10],)):
        if archive_path(memory, row[0]).is_file():
            return row[0]
    return None


def backup(memory: MemoryStore, *, daily: bool = False) -> dict:
    memory.expire()
    policy = load_policy()
    with memory.access() as (control, _):
        if vault_id(control) is None:
            with open_vault(memory, control, setup=True):
                pass
    with memory.access() as (control, db), open_vault(memory, control) as (vault, identity, head):
        if head != seen_markers(control):
            raise MemoryRefusal("ledger_unverified", "Le registre courant diffère du coffre.")
        now = memory.clock()
        rotate(memory, vault, now, policy)
        if daily:
            if not policy["backup"]["daily"]:
                return {"status": "disabled_by_policy"}
            if found := todays_archive(memory, vault, now):
                return {"status": "already_backed_up", "id": found}
        values = []
        for row in db.execute("SELECT * FROM memory_items WHERE scope = ? ORDER BY rowid", (NOTES_SCOPE,)):
            item_id = row["id"]
            try:
                memory.require(control, db, item_id, scope=NOTES_SCOPE, now=now, policy=policy)
            except MemoryRefusal as error:
                if error.code not in {"erasure_requested", "retention_expired", "redacted_by_deletion"}:
                    raise
                continue
            parents = [parent[0] for parent in db.execute("SELECT parent FROM memory_lineage WHERE child = ? ORDER BY parent",
                                                          (item_id,))]
            value = {"row": dict(row), "parents": parents}
            value["row"]["expires_at"] = stamp(expiration(row, policy))
            values.append(value)

    # Le chiffrement d'une génération ne bloque pas une demande d'effacement.
    issued = now
    backup_id = str(uuid4())
    path = archive_path(memory, backup_id)
    package = {"format": FORMAT, "vault": identity, "id": backup_id, "items": {}}
    keys = []
    links = []
    for value in values:
        row = value["row"]
        item_id = row["id"]
        encrypted = crypto("encrypt", data=encode(pack(value)), aad=aad(identity, backup_id, item_id))
        keys.append((backup_id, item_id, encrypted.pop("key"), row["kind"] == "trace",
                     row["created_at"], row["expires_at"], row["retention"]))
        links.extend((backup_id, item_id, parent) for parent in value["parents"])
        package["items"][item_id] = encrypted
    values.clear()

    limit = configured_limit()

    with memory.access() as (control, db), open_vault(memory, control) as (vault, current, head):
        if identity != current or head != seen_markers(control):
            raise MemoryRefusal("ledger_unverified", "Le registre courant diffère du coffre.")
        now = memory.clock()
        policy = load_policy()
        if daily and (found := todays_archive(memory, vault, now)):
            return {"status": "already_backed_up", "id": found}
        for item_id in package["items"]:
            memory.require(control, db, item_id, scope=NOTES_SCOPE, now=now, policy=policy)
        if limit is not None and used_bytes(memory) + len(pack(package)) > limit:
            raise MemoryRefusal("storage_budget_exceeded", "Le coffre ne dispose pas d'assez d'espace autorisé.")
        vault.execute("INSERT INTO archives VALUES (?, ?, ?, ?)", (backup_id, stamp(issued),
                      stamp(deadline(issued, "backup", policy=policy)), digest(pack(package))))
        vault.executemany("INSERT INTO keys VALUES (?, ?, ?, ?, ?, ?, ?)", keys)
        vault.executemany("INSERT INTO backup_lineage VALUES (?, ?, ?)", links)
        publish(path, package)
    record(memory.path, action="memory_backup", risk="R1", actor="policy" if daily else "user", decision="verified")
    return {"status": "backed_up", "id": backup_id, "items": len(keys)}


def restore(memory: MemoryStore, backup_id: str) -> dict:
    path = archive_path(memory, backup_id)
    policy = load_policy()
    with memory.access() as (control, _), open_vault(memory, control) as (vault, identity, head):
        if head != seen_markers(control):
            raise MemoryRefusal("ledger_unverified", "Le registre courant diffère du coffre.")
        current = vault.execute("SELECT * FROM archives WHERE id = ?", (backup_id,)).fetchone()
        now = memory.clock()
        if current is None or now >= deadline(datetime.fromisoformat(current["issued"]), "backup",
                parent_deadlines=(datetime.fromisoformat(current["expires"]),), policy=policy):
            raise MemoryRefusal("archive_expired", "La génération n'est plus restaurable.")
        raw = path.read_bytes()
        if digest(raw) != current["envelope_digest"]:
            raise MemoryRefusal("archive_unverified", "L'enveloppe de sauvegarde a changé.")
        package = json.loads(raw)
        if (package["vault"], package["format"], package["id"]) != (identity, FORMAT, backup_id):
            raise MemoryRefusal("archive_unverified", "L'enveloppe ne correspond pas au coffre.")
        erased = {marker[0] for marker in head}
        keys = {}
        for item_id in package["items"]:
            if item_id in erased:
                continue
            key = vault.execute("SELECT wrapped FROM keys WHERE backup = ? AND item = ?", (backup_id, item_id)).fetchone()
            if key is None:
                raise MemoryRefusal("archive_unverified", "Clé inattendue manquante.")
            keys[item_id] = key[0]

    staged = {}
    for item_id, wrapped in keys.items():
        encrypted = package["items"][item_id]
        value = json.loads(decode(crypto("decrypt", **encrypted, key=wrapped, aad=aad(identity, backup_id, item_id))["data"]))
        if value["row"]["id"] != item_id or value["row"]["scope"] != NOTES_SCOPE:
            raise MemoryRefusal("archive_unverified", "Objet restauré hors périmètre.")
        if expiration(value["row"], policy) > now and not erased.intersection(value["parents"]):
            staged[item_id] = value
    keys.clear()

    with memory.access() as (control, db), open_vault(memory, control) as (vault, latest, latest_head):
        if identity != latest or head != latest_head or head != seen_markers(control):
            raise MemoryRefusal("ledger_unverified", "Le registre a changé avant la publication de la restauration.")
        if vault.execute("SELECT 1 FROM archives WHERE id = ? AND envelope_digest = ?",
                         (backup_id, current["envelope_digest"])).fetchone() is None:
            raise MemoryRefusal("archive_unverified", "La génération n'est plus disponible.")
        now = memory.clock()
        policy = load_policy()
        if now >= deadline(datetime.fromisoformat(current["issued"]), "backup",
                           parent_deadlines=(datetime.fromisoformat(current["expires"]),), policy=policy):
            raise MemoryRefusal("archive_expired", "La génération n'est plus restaurable.")
        restored = 0
        while staged:
            ready = [item for item, value in staged.items() if not (staged.keys() & set(value["parents"]))]
            if not ready:
                raise MemoryRefusal("archive_unverified", "Filiation cyclique dans la sauvegarde.")
            for item_id in ready:
                value = staged.pop(item_id)
                if row_for(db, item_id) is not None or expiration(value["row"], policy) <= now:
                    continue
                for parent in value["parents"]:
                    try:
                        memory.require(control, db, parent, scope=NOTES_SCOPE, now=now, policy=policy)
                    except MemoryRefusal as error:
                        if error.code not in {"missing_object", "erasure_requested", "retention_expired",
                                              "redacted_by_deletion"}:
                            raise
                        break
                else:
                    db.execute("INSERT INTO memory_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                               tuple(value["row"][name] for name in COLUMNS))
                    db.executemany("INSERT INTO memory_lineage VALUES (?, ?)",
                                   ((item_id, parent) for parent in value["parents"]))
                    restored += 1
    record(memory.path, action="memory_restore", risk="R1", actor="user", decision="verified")
    return {"status": "restored", "added": restored, "erased_omitted": len(erased & package["items"].keys())}


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    make = commands.add_parser("backup")
    make.add_argument("--daily", action="store_true")
    commands.add_parser("watch", help="Appliquer la rétention et la sauvegarde quotidienne")
    load = commands.add_parser("restore")
    load.add_argument("id")
    args = parser.parse_args()
    memory = MemoryStore(args.db)
    if args.action == "watch":
        previous = None
        try:
            while True:
                disk = None
                try:
                    memory.expire()
                    disk = enforce(memory)
                    result = backup(memory, daily=True)
                except (MemoryRefusal, OSError, ProjectError, sqlite3.Error, ValueError) as error:
                    result = {"status": "pending", "code": getattr(error, "code", "storage_unverified")}
                if disk is not None:
                    result["disk"] = disk
                if result != previous:
                    print(json.dumps(result), flush=True)
                    previous = result
                sleep(60)
        except KeyboardInterrupt:
            return 0
    try:
        result = backup(memory, daily=args.daily) if args.action == "backup" else restore(memory, args.id)
    except (MemoryRefusal, OSError, ProjectError, sqlite3.Error, ValueError, KeyError) as error:
        print(json.dumps({"status": "refused", "code": getattr(error, "code", "storage_unverified")}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
