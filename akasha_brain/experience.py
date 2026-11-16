"""Journal local des résultats techniques du banc synthétique Notes."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from contracts.akasha_contracts.validate import validate

from .planning import PlanningError
from .retention import DEFAULT_POLICY, deadline, load_policy

TECHNICAL_RESULTS = {
    "localize": ("tests", "failures", "errors", "skips", "pytest_exit"),
    "generate_diff": ("diff_applied", "git_apply_check", "guest_sha256_verified"),
    "adapt_patch_receipt": ("input_name", "diff_sha256", "conversion_ms"),
    "prepare_reference": ("reference_sha256_verified_in_guest",),
    "verify": ("passed", "pytest_exit", "sqlite_verifier_exit"),
    "verify_desktop": ("guest_exit_code", "desktop"),
}


@contextmanager
def transaction(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        yield connection


def ensure_experience_table(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS experiences (
        record_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, origin TEXT NOT NULL,
        record TEXT NOT NULL, expires_at TEXT
    )""")
    if not any(column[1] == "expires_at" for column in db.execute("PRAGMA table_info(experiences)")):
        db.execute("ALTER TABLE experiences ADD COLUMN expires_at TEXT")


def record_experience(path: Path, report: dict, origin: str) -> str:
    created = datetime.now(timezone.utc)
    graph = report["graph"]
    checks = []
    for step in report["trace"]:
        result = step.get("result", {})
        checks.append({
            "id": step["id"], "status": step["status"], "wall_s": step["wall_s"],
            "result": {key: result[key] for key in TECHNICAL_RESULTS[step["id"]] if key in result},
        })
    record = {
        "record_id": str(uuid4()),
        "goal_id": graph["goal_id"],
        "graph_version": graph["graph_version"],
        "node_versions": [{key: step[key] for key in ("capability_id", "version")} for step in graph["steps"]],
        "verification": {
            "status": "pass" if report["status"] == "passed" else "fail",
            "predicate_results": checks,
        },
        "cost": {"wall_s": report["wall_s"]},
        "contains_user_content": False,
        "created_at": created.isoformat(),
    }
    if error := report.get("error"):
        record["errors"] = [{key: error[key] for key in ("code", "family")}]
    if errors := validate(record, "ExperienceRecord"):
        raise PlanningError(errors[0])
    with transaction(path) as db:
        db.execute("BEGIN IMMEDIATE")
        ensure_experience_table(db)
        db.execute("INSERT INTO experiences (record_id, graph_id, origin, record, expires_at) VALUES (?, ?, ?, ?, ?)",
                   (record["record_id"], graph["graph_id"], origin, json.dumps(record),
                    deadline(created, "minimized_results").isoformat()))
    return record["record_id"]


def prune_experiences(path: Path, *, now: datetime | None = None) -> int:
    if not path.is_file():
        return 0
    moment = now or datetime.now(timezone.utc)
    policy = load_policy()
    with transaction(path) as db:
        db.execute("PRAGMA secure_delete = ON")
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'experiences' AND type = 'table'").fetchone():
            return 0
        ensure_experience_table(db)
        expired = []
        for record_id, created, stored in db.execute(
            "SELECT record_id, json_extract(record, '$.created_at'), expires_at FROM experiences"
        ):
            origin = datetime.fromisoformat(created)
            limit = (datetime.fromisoformat(stored) if stored else
                     deadline(origin, "minimized_results", policy=DEFAULT_POLICY))
            expiration = deadline(origin, "minimized_results", parent_deadlines=(limit,), policy=policy)
            if moment >= expiration:
                expired.append((record_id,))
            elif stored != expiration.isoformat():
                db.execute("UPDATE experiences SET expires_at = ? WHERE record_id = ?", (expiration.isoformat(), record_id))
        deleted = db.executemany("DELETE FROM experiences WHERE record_id = ?", expired).rowcount
        db.commit()
        if db.execute("PRAGMA journal_mode").fetchone()[0] == "wal" and db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            raise OSError("La purge du journal SQLite réinscriptible reste en attente.")
    return deleted
