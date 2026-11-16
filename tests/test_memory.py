from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from akasha_brain import project_audit
from akasha_brain.experience import transaction
from akasha_brain.memory import NOTES_SCOPE, NotesMemory
from akasha_brain.memory_store import MemoryRefusal
from akasha_brain.retention import load_policy

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)
SAMPLE = Path(__file__).resolve().parents[1] / "bench" / "results" / "notes-evolution-ram-v1.json"


def journal(path, count):
    entries = json.loads(SAMPLE.read_bytes())["experiences"]
    ids = []
    with transaction(path) as db:
        db.execute("CREATE TABLE experiences (record_id TEXT PRIMARY KEY, graph_id TEXT, origin TEXT, record TEXT)")
        for index in range(count):
            entry = entries[index % len(entries)]
            item_id = str(uuid4())
            ids.append(item_id)
            record = {**entry["record"], "record_id": item_id, "goal_id": str(uuid4()), "created_at": NOW.isoformat()}
            db.execute("INSERT INTO experiences VALUES (?, ?, ?, ?)",
                       (item_id, entry["graph_id"], entry["origin"], json.dumps(record)))
    return ids


def test_capture_moves_only_allowlisted_fields_and_maintains_a_paginated_window(tmp_path):
    path = tmp_path / "notes.sqlite"
    ids = journal(path, 35)
    with transaction(path) as db:
        db.execute("""UPDATE experiences SET record = json_set(record,
            '$.verification.predicate_results[0].result.private_value', 'discard-this') WHERE record_id = ?""", (ids[0],))
        db.execute("""UPDATE experiences SET record = json_set(record, '$.contains_user_content', json('true'))
                      WHERE record_id = ?""", (ids[-1],))
    memory = NotesMemory(path, clock=lambda: NOW)
    memory.initialize()
    assert memory.capture([ids[0]]) == {"captured": 1, "excluded": 0, "expired": 0}
    assert "discard-this" not in json.dumps(memory.experience(ids[0]))
    assert memory.capture() == {"captured": 33, "excluded": 1, "expired": 0}
    with transaction(path) as db:
        assert db.execute("SELECT record_id FROM experiences").fetchall() == [(ids[-1],)]
    window = memory.open_window(ids[0], ids[:-1])
    cursor = 0
    read = []
    while cursor is not None:
        page = memory.page(window, cursor)
        assert len(page["items"]) <= 4
        read.extend(entry["record"]["record_id"] for entry in page["items"])
        cursor = page["next_cursor"]
    assert read == ids[2:-1]
    assert memory.close_window(window) == {"status": "verified", "removed": 1}
    assert memory.experience(ids[0])["working_memory"]["eviction"] == "oldest_first"


def test_bitemporal_fact_uses_transaction_time_and_exclusive_validity_end(tmp_path):
    path = tmp_path / "notes.sqlite"
    original, *_, correction = journal(path, 6)
    with transaction(path) as db:
        trace = '$.verification.predicate_results[2]'
        db.execute(f"""UPDATE experiences SET graph_id = 'notes-rbitnet', record = json_set(
            json_remove(record, '$.node_versions[3]', '$.verification.predicate_results[3]'),
            '$.verification.status', 'fail', '{trace}.status', 'failed', '{trace}.result.sqlite_verifier_exit', 1)
            WHERE record_id = ?""", (correction,))
    clock = [NOW]
    memory = NotesMemory(path, clock=lambda: clock[0])
    memory.initialize()
    memory.capture()
    yesterday = NOW - timedelta(days=1)
    first = memory.record_fact(original, "sqlite_verified", yesterday)
    clock[0] += timedelta(minutes=1)
    second = memory.record_fact(correction, "sqlite_verified", yesterday, NOW)
    args = ("notes-rbitnet", "sqlite_verified")
    assert memory.fact_at(*args, yesterday, recorded_as_of=NOW)["id"] == first
    assert memory.fact_at(*args, yesterday)["value"] is False
    assert memory.fact_at(*args, NOW)["value"] is True
    memory.request_erasure(correction)
    assert memory.fact_at(*args, yesterday)["value"] is True
    assert memory.finish_erasures() == {"status": "verified", "removed": 2}
    with transaction(path) as db:
        assert db.execute("SELECT 1 FROM memory_items WHERE id = ?", (second,)).fetchone() is None


def test_erasure_is_immediate_for_all_derivatives_and_recovers_after_failure(tmp_path):
    path = tmp_path / "notes.sqlite"
    (source,) = journal(path, 1)
    memory = NotesMemory(path, clock=lambda: NOW)
    memory.initialize()
    memory.capture()
    window = memory.open_window(source, [source])
    with memory.access() as (control, db):
        artifact = memory.save(control, db, kind="artifact", scope=NOTES_SCOPE, payload="prune-marker-1745",
                               now=NOW, policy=load_policy(), parents=(window,))
        trace = memory.save(control, db, kind="trace", scope=NOTES_SCOPE, payload={"artifact": artifact},
                            now=NOW, policy=load_policy(), parents=(artifact,))
        db.execute("""CREATE TRIGGER simulate_erase_failure BEFORE DELETE ON memory_items
                      BEGIN SELECT RAISE(ABORT, 'unavailable'); END""")
    memory.request_erasure(source)
    assert memory.inventory() == []
    with pytest.raises(MemoryRefusal, match="en cours d'effacement"):
        memory.page(window)
    with pytest.raises(sqlite3.IntegrityError, match="unavailable"):
        memory.finish_erasures()
    with memory.access() as (control, db):
        with pytest.raises(MemoryRefusal, match="Trace expurgée") as refusal:
            memory.require(control, db, trace, scope=NOTES_SCOPE, now=NOW, policy=load_policy())
        assert refusal.value.code == "redacted_by_deletion"
        assert db.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 4
        db.execute("DROP TRIGGER simulate_erase_failure")
    assert memory.finish_erasures() == {"status": "verified", "removed": 4}
    with memory.access() as (control, db):
        assert db.execute("SELECT COUNT(*) FROM memory_lineage").fetchone()[0] == 0
        assert control.execute("SELECT MIN(verified) FROM memory_erasures").fetchone()[0] == 1
    audit = path.parent / project_audit.LOG_NAME
    assert project_audit.verify(audit) == {"status": "passed", "entries_verified": 2}
    assert b"prune-marker-1745" not in path.read_bytes()
    for item in (source, window, artifact, trace):
        assert item.encode() not in audit.read_bytes()


def test_derived_deadline_is_inherited_and_the_erasure_registry_is_mandatory(tmp_path):
    path = tmp_path / "notes.sqlite"
    (source,) = journal(path, 1)
    clock = [NOW]
    memory = NotesMemory(path, clock=lambda: clock[0])
    memory.initialize()
    memory.capture()
    clock[0] += timedelta(days=89)
    memory.open_window(source, [source])
    assert len({item["expires_at"] for item in memory.inventory()}) == 1
    clock[0] += timedelta(days=1)
    assert memory.inventory() == []
    assert memory.expire() == {"status": "verified", "removed": 2}
    memory.control.rename(memory.control.with_suffix(".quarantined"))
    with pytest.raises(MemoryRefusal, match="indisponible"):
        memory.experience(source)
    with pytest.raises(MemoryRefusal, match="manquant"):
        memory.initialize()


def test_rollback_disables_retrieval_and_erasure_waits_for_scratch(tmp_path):
    from akasha_brain.memory_scratch import run_folder, scratch_lease
    from akasha_brain.memory_workflows import PARENT_REVISION, WorkflowLibrary

    path = tmp_path / "notes.sqlite"
    (source,) = journal(path, 1)
    memory = NotesMemory(path, clock=lambda: NOW)
    memory.initialize()
    memory.capture()
    library = WorkflowLibrary(memory)
    library.install()
    scratch = run_folder(memory, str(uuid4()))
    with scratch_lease(scratch):
        scratch.mkdir()
        (scratch / "derived.txt").write_bytes(b"pending-disposable-object")
        with memory.access() as (_, db):
            db.execute("INSERT INTO memory_scratch VALUES (?, ?)", (scratch.name, source))
        memory.request_erasure(source)
        with pytest.raises(MemoryRefusal, match="en cours"):
            memory.finish_erasures()
    with memory.access() as (_, db):
        assert db.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 1
    assert memory.finish_erasures()["status"] == "verified"
    assert not scratch.exists()
    assert library.rollback()["version"] == PARENT_REVISION
    assert memory.capture()["status"] == "disabled"
    with pytest.raises(MemoryRefusal, match="désactivée"):
        memory.experience(source)


def test_disk_pressure_evicts_the_oldest_orphan_and_protects_referenced_artifacts(tmp_path):
    from akasha_brain.memory_budget import enforce, used_bytes

    memory = NotesMemory(tmp_path / "notes.sqlite", clock=lambda: NOW)
    memory.initialize()
    with memory.access() as (control, db):
        fields = {"control": control, "db": db, "now": NOW, "policy": load_policy(), "scope": NOTES_SCOPE}
        oldest = memory.save(**fields, kind="artifact", payload="O" * 32000, created_at=NOW - timedelta(hours=2))
        newer = memory.save(**fields, kind="artifact", payload="N" * 32000, created_at=NOW - timedelta(hours=1))
        protected = memory.save(**fields, kind="artifact", payload="P" * 32000)
        memory.save(**fields, kind="trace", payload={"verified": True}, parents=(protected,))
    result = enforce(memory, limit=used_bytes(memory) - 16000)
    assert result["status"] == "within_budget" and result["evicted"] == 1
    inventory = {record["id"] for record in memory.inventory()}
    assert oldest not in inventory and {newer, protected} <= inventory
    result = enforce(memory, limit=1)
    assert result["status"] == "over_budget" and result["evicted"] == 1
    assert protected in {record["id"] for record in memory.inventory()}
