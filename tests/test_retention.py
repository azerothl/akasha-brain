from datetime import datetime, timedelta, timezone
import json

from akasha_brain.experience import prune_experiences, transaction
from akasha_brain.retention import DEFAULT_POLICY, copy_deadline, deadline


def test_retention_windows_and_shorter_source_deadline():
    created = datetime(2026, 11, 16, tzinfo=timezone.utc)
    for kind, days in (("minimized_results", 90), ("real_contents", 30), ("captures", 7), ("backup", 7)):
        assert deadline(created, kind, policy=DEFAULT_POLICY) == created + timedelta(days=days)
    source = created + timedelta(days=2)
    assert deadline(created, "backup", parent_deadlines=(source,), policy=DEFAULT_POLICY) == source
    longer = {**DEFAULT_POLICY, "windows_days": {**DEFAULT_POLICY["windows_days"], "real_contents": 60}}
    assert copy_deadline(created.isoformat(), source.isoformat(), policy=longer) == source


def test_legacy_experience_pruning_migrates_without_extending_the_deadline(tmp_path, monkeypatch):
    path = tmp_path / "registry.db"
    created = datetime(2026, 11, 16, tzinfo=timezone.utc)
    with transaction(path) as db:
        db.execute("CREATE TABLE experiences (record_id TEXT PRIMARY KEY, graph_id TEXT, origin TEXT, record TEXT)")
        db.execute("INSERT INTO experiences VALUES ('old', 'graph', 'task', ?)",
                   (json.dumps({"created_at": created.isoformat()}),))
    policy = {**DEFAULT_POLICY, "windows_days": {**DEFAULT_POLICY["windows_days"], "minimized_results": 7}}
    configured = tmp_path / "policy.json"
    configured.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setenv("AKASHA_RETENTION_POLICY", str(configured))
    assert prune_experiences(path, now=created + timedelta(days=7, microseconds=-1)) == 0
    monkeypatch.delenv("AKASHA_RETENTION_POLICY")
    assert prune_experiences(path, now=created + timedelta(days=7)) == 1
    with transaction(path) as db:
        assert db.execute("SELECT COUNT(*) FROM experiences").fetchone() == (0,)
