"""Éprouve deux générations chiffrées et la reprise d'un effacement Notes."""

from argparse import ArgumentParser
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

from akasha_brain.memory import NOTES_SCOPE, NotesMemory
from akasha_brain.memory_backup import archive_path, backup, restore, vault_path
from akasha_brain.memory_store import MemoryRefusal, utc_now
from akasha_brain.memory_workflows import WorkflowLibrary
from akasha_brain.project_audit import LOG_NAME, verify
from akasha_brain.retention import load_policy
from bench.run_guided_repair import write_report


def sqlite_copy(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old, closing(sqlite3.connect(target)) as copy:
        old.backup(copy)


def refusal(call, code):
    try:
        call()
    except MemoryRefusal as error:
        assert error.code == code, error.code
    else:
        raise AssertionError(f"Refus attendu ({code}).")


def measure(phase1: Path, directory: Path) -> dict:
    directory.mkdir(parents=True)
    clock = [utc_now()]
    memory = NotesMemory(directory / "journal.sqlite", clock=lambda: clock[0])
    sqlite_copy(phase1 / "registry.db", memory.path)
    memory.initialize()
    memory.capture()
    library = WorkflowLibrary(memory)
    library.install()
    code = library.publish([phase1 / name / "report.json" for name in ("cycle", "rollback-proof")])
    reports = [phase1 / "cycle" / "evolution" / stage / "report.json" for stage in ("replay", "shadow", "limited")]
    desktop = library.publish(reports)
    forgotten = json.loads(reports[0].read_bytes())["experience_record_id"]
    window = memory.open_window(forgotten, [forgotten])
    fact = memory.record_fact(forgotten, "desktop_verified", clock[0])
    with memory.access() as (control, db):
        trace = memory.save(control, db, kind="trace", scope=NOTES_SCOPE, parents=(desktop["index"],),
                            payload={"index": desktop["index"], "outcome": {"status": "passed"}},
                            now=clock[0], policy=load_policy())
        short_lived = memory.save(control, db, kind="artifact", scope=NOTES_SCOPE, payload={"synthetic": True},
                                  now=clock[0], prior_deadline=clock[0] + timedelta(days=2), policy=load_policy())
    generations = [backup(memory, daily=True)]
    assert backup(memory, daily=True)["status"] == "already_backed_up"
    clock[0] += timedelta(days=1)
    generations.append(backup(memory, daily=True))
    archived = {gen["id"]: archive_path(memory, gen["id"]).read_bytes() for gen in generations}
    assert len(archived) == 2 and len(set(archived.values())) == 2
    assert all(b"desktop_verified" not in raw and b"INSERT INTO notes" not in raw for raw in archived.values())
    stale = directory / "registra-ante-effacement.sqlite"
    sqlite_copy(memory.control, stale)

    # Simule une perte partielle du stockage actif. La trace demeure dans les deux sauvegardes.
    with memory.access() as (_, db):
        db.execute("DELETE FROM memory_items WHERE id = ?", (trace,))

    vault = vault_path(memory)
    offline = vault.with_suffix(".offline")
    vault.rename(offline)
    try:
        memory.request_erasure(forgotten)
        refusal(lambda: memory.experience(forgotten), "erasure_requested")
        refusal(lambda: memory.page(window), "erasure_requested")
        refusal(memory.finish_erasures, "ledger_unverified")
        refusal(lambda: restore(memory, generations[0]["id"]), "ledger_unverified")
    finally:
        offline.rename(vault)
    refusal(lambda: restore(memory, generations[0]["id"]), "ledger_unverified")
    assert memory.finish_erasures() == {"status": "verified", "removed": 8}
    with memory.access() as (control, db):
        refusal(lambda: memory.require(control, db, trace, scope=NOTES_SCOPE, now=clock[0], policy=load_policy()),
                "redacted_by_deletion")
    with memory.access() as (control, db):
        removed = {row[0] for row in control.execute("SELECT id FROM memory_erasures WHERE verified = 1")}
        assert {forgotten, fact, trace, window, desktop["workflow"], desktop["index"]} <= removed
        assert len(removed) == 8
    with closing(sqlite3.connect(vault.as_uri() + "?mode=ro", uri=True)) as reads:
        keys = reads.execute("SELECT backup, item FROM keys").fetchall()
        assert sum(item in removed for _, item in keys) == 0
        assert {gen["id"] for gen in generations} == {entry for entry, item in keys if item == code["index"]}

    current = directory / "controle-courant.sqlite"
    memory.control.rename(current)
    try:
        refusal(lambda: restore(memory, generations[0]["id"]), "ledger_unverified")
        stale.rename(memory.control)
        try:
            refusal(lambda: restore(memory, generations[0]["id"]), "ledger_unverified")
        finally:
            memory.control.rename(stale)
    finally:
        current.rename(memory.control)

    results = []
    for gen in generations:
        with memory.access() as (_, db):
            db.execute("DELETE FROM memory_items")
        assert archive_path(memory, gen["id"]).read_bytes() == archived[gen["id"]]
        result = restore(memory, gen["id"])
        assert result == {"status": "restored", "added": 10, "erased_omitted": 8}, result
        inventory = {item["id"] for item in memory.inventory()}
        assert code["index"] in inventory and not removed & inventory
        results.append(result)
    with memory.access() as (_, db):
        db.execute("DELETE FROM memory_items WHERE id = ?", (short_lived,))
    clock[0] += timedelta(days=1)
    assert memory.expire() == {"status": "verified", "removed": 1}
    with closing(sqlite3.connect(vault.as_uri() + "?mode=ro", uri=True)) as reads:
        assert reads.execute("SELECT COUNT(*) FROM keys WHERE item = ?", (short_lived,)).fetchone()[0] == 0
    for gen in generations:
        assert restore(memory, gen["id"])["erased_omitted"] == 9
    clock[0] += timedelta(days=6)
    backup(memory, daily=True)
    for gen in generations:
        assert not archive_path(memory, gen["id"]).exists()
        refusal(lambda: restore(memory, gen["id"]), "archive_expired")
    result = {
        "status": "passed", "encrypted_generations": len(generations), "objects_per_generation": 18,
        "erased_objects": len(removed), "archive_only_trace_erased": True, "keys_removed": len(removed) * len(generations),
        "blocked_at_request": True, "temporary_vault_loss_recovered": True, "missing_or_old_ledger_refused": True,
        "restores": results, "archive_only_expiry_verified": True,
        "expired_generations_rotated": True, "audit": verify(directory / LOG_NAME),
    }
    write_report(directory, result)
    return result


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--phase1", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(measure(args.phase1.resolve(strict=True), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
