"""Évolution versionnée dans le seul banc synthétique Notes."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import monotonic
from uuid import uuid4

from bench.run_guided_repair import execution_limits, write_report
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .evolution_consent import ReuseScope, check_reuse
from .experience import transaction
from .notes_repair import RbitnetPaths
from .notes_runtime import run_notes
from .planning import PlanningError, compile_goal

PARENT = "notes-rbitnet"
CANDIDATE = "notes-rbitnet-ocr"
STAGES = ("replay", "shadow", "limited")
GOAL_FILE = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "goal_notes_regression.json"


@dataclass(frozen=True)
class EvolutionBudget:
    wall_s: int
    max_trials: int
    cpu_threads: int
    model_ram_mb: int


@contextmanager
def lease(path: Path):
    with transaction(path.with_suffix(".lease.db")) as db:
        db.execute("PRAGMA busy_timeout = 0")
        try:
            db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            raise PlanningError(AkashaError(
                ErrorCode.RESOURCE_BUDGET_EXCEEDED, "Le banc Notes a déjà une exécution en cours.",
            )) from exc
        yield


def audit(db, cycle_id: str, event: str, details: dict) -> None:
    last = db.execute("SELECT digest FROM evolution_events ORDER BY seq DESC LIMIT 1").fetchone()
    previous = last[0] if last else None
    entry = {"created_at": datetime.now(timezone.utc).isoformat(), "cycle_id": cycle_id,
             "event": event, "details": details, "previous": previous}
    payload = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    db.execute("INSERT INTO evolution_events (payload, digest) VALUES (?, ?)",
               (payload, sha256(payload.encode("utf-8")).hexdigest()))


def initialize(path: Path, catalog: dict) -> dict:
    goal = json.loads(GOAL_FILE.read_text(encoding="utf-8"))
    plans = [compile_goal(goal, catalog, rbitnet=True, rapidocr=desktop) for desktop in (False, True)]
    parent, candidate = plans
    if parent["steps"] != candidate["steps"][:-1] or candidate["steps"][-1]["depends_on"] != ["verify"]:
        raise RuntimeError("Le candidat doit conserver les contrôles du parent et ajouter le contrôle bureau.")
    with transaction(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS workflow_versions (
            id TEXT PRIMARY KEY, parent TEXT REFERENCES workflow_versions(id), plan TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS active_workflow (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            workflow TEXT NOT NULL REFERENCES workflow_versions(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS evolution_events (
            seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL
        )""")
        for plan, base in zip(plans, (None, PARENT)):
            snapshot = json.dumps(plan, sort_keys=True)
            graph_id = plan["graph_id"]
            db.execute("INSERT OR IGNORE INTO workflow_versions VALUES (?, ?, ?)", (graph_id, base, snapshot))
            if db.execute("SELECT plan FROM workflow_versions WHERE id = ?", (graph_id,)).fetchone()[0] != snapshot:
                raise RuntimeError("Une version de graphe enregistrée a changé.")
        db.execute("INSERT OR IGNORE INTO active_workflow VALUES (1, ?)", (PARENT,))
    return goal


def active_workflow(db) -> str:
    return db.execute("SELECT workflow FROM active_workflow WHERE singleton = 1").fetchone()[0]


def evolution_status(path: Path) -> dict:
    with transaction(path) as db:
        active = active_workflow(db)
        versions = [
            {"id": key, "version": json.loads(plan)["graph_version"], "parent": parent}
            for key, parent, plan in db.execute("SELECT id, parent, plan FROM workflow_versions ORDER BY id")
        ]
        events = [{"entry": json.loads(payload), "digest": digest}
                  for payload, digest in db.execute("SELECT payload, digest FROM evolution_events ORDER BY seq")]
    return {"active": active, "versions": versions, "events": events}


def rollback(path: Path) -> dict:
    with lease(path), transaction(path) as db:
        db.execute("BEGIN IMMEDIATE")
        active = active_workflow(db)
        parent = db.execute("SELECT parent FROM workflow_versions WHERE id = ?", (active,)).fetchone()[0]
        if parent is None:
            raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Aucun parent à restaurer."))
        db.execute("UPDATE active_workflow SET workflow = ? WHERE singleton = 1", (parent,))
        audit(db, str(uuid4()), "rolled_back", {"previous_active": active, "active": parent})
    return {"previous_active": active, "active": parent}


def evidence(report: dict, *, desktop: bool) -> dict:
    trace = {step["id"]: step for step in report["trace"]}
    patch = trace.get("generate_diff", {}).get("result", {})
    tests = trace.get("verify", {}).get("result", {})
    observation = trace.get("verify_desktop", {}).get("result", {})
    return {
        "verified": (report["status"] == "passed" and report.get("sandbox_stopped") is True
                     and report.get("experience_record_id") is not None
                     and bool(report.get("isolation")) and all(report["isolation"].values())
                     and all(step.get("authorization") == "allowed" for step in trace.values())
                     and report.get("accepted_attempt") == 1 and patch.get("diff_applied") is True
                     and patch.get("git_apply_check") is True and patch.get("guest_sha256_verified") is True
                     and tests.get("passed") == 4 and tests.get("pytest_exit") == tests.get("sqlite_verifier_exit") == 0
                     and (not desktop or (observation.get("guest_exit_code") == 0x471F
                                         and patch.get("matches_desktop_protocol") is True))),
        "experience": report.get("experience_record_id"),
        "wall_s": report["wall_s"],
        "diff": patch.get("diff_sha256"),
    }


def evolve(path: Path, cycle_id: str, budget: EvolutionBudget, reference: dict, run_trial,
           *, reuse: tuple[ReuseScope, ...] = ()) -> dict:
    started = monotonic()
    deadline = started + budget.wall_s
    trials = []

    def finish(status: str, reason: str) -> dict:
        result = {"cycle_id": cycle_id, "status": status, "reason": reason, "trials": trials,
                  "wall_s": round(monotonic() - started, 3)}
        with transaction(path) as db:
            audit(db, cycle_id, status, {key: value for key, value in result.items() if key != "trials"})
        return result

    if reuse:
        with transaction(path) as db:
            denied = check_reuse(db, reuse)
        if denied:
            return finish("retained", denied.details["reason"])
    if budget.max_trials < len(STAGES) or budget.wall_s <= 0:
        return finish("waiting", "resource_budget_exceeded")

    sandbox_ids = {reference.get("sandbox_id")}
    expected = evidence(reference, desktop=False)
    for stage in STAGES:
        if monotonic() >= deadline:
            return finish("waiting", "resource_budget_exceeded")
        with transaction(path) as db:
            if reuse:
                db.execute("BEGIN IMMEDIATE")
            denied = check_reuse(db, reuse)
            parent_active = active_workflow(db) == PARENT
            if denied is None and parent_active:
                audit(db, cycle_id, "trial_started", {"stage": stage, "parent": PARENT, "candidate": CANDIDATE})
        if denied:
            return finish("retained", denied.details["reason"])
        if not parent_active:
            return finish("retained", "active_workflow_changed")
        with execution_limits(deadline, budget.cpu_threads, budget.model_ram_mb):
            report = run_trial(stage)
        if reuse:
            with transaction(path) as db:
                denied = check_reuse(db, reuse)
            if denied:
                return finish("retained", denied.details["reason"])
        proof = evidence(report, desktop=True)
        proof["fresh_sandbox"] = bool(report.get("sandbox_id")) and report["sandbox_id"] not in sandbox_ids
        sandbox_ids.add(report.get("sandbox_id"))
        trial = {"stage": stage, **proof}
        trials.append(trial)
        with transaction(path) as db:
            audit(db, cycle_id, "trial_finished", {key: value for key, value in trial.items() if key != "diff"})
        if monotonic() >= deadline or report.get("error", {}).get("code") == ErrorCode.RESOURCE_BUDGET_EXCEEDED.value:
            return finish("waiting", "resource_budget_exceeded")
        if not expected["verified"] or not proof["verified"] or not proof["fresh_sandbox"] or proof["diff"] != expected["diff"]:
            return finish("retained", "insufficient_evidence")

    with transaction(path) as db:
        db.execute("BEGIN IMMEDIATE")
        denied = check_reuse(db, reuse)
        if denied is None and monotonic() < deadline and active_workflow(db) == PARENT:
            db.execute("UPDATE active_workflow SET workflow = ? WHERE singleton = 1", (CANDIDATE,))
            audit(db, cycle_id, "activated", {"parent": PARENT, "active": CANDIDATE,
                                             "reference": expected["experience"],
                                             "evidence": [trial["experience"] for trial in trials]})
            return {"cycle_id": cycle_id, "status": "promoted", "active": CANDIDATE, "trials": trials,
                    "wall_s": round(monotonic() - started, 3)}
    return finish("retained", denied.details["reason"] if denied else "promotion_precondition_changed")


def run_managed(goal: dict, catalog: dict, runtime: Path, output: Path, repair: RbitnetPaths,
                path: Path, budget: EvolutionBudget) -> dict:
    with lease(path):
        synthetic_goal = initialize(path, catalog)
        if goal != synthetic_goal:
            raise PlanningError(AkashaError(
                ErrorCode.PERMISSION_DENIED, "L'évolution est réservée à l'objectif synthétique Notes figé.",
            ))
        with transaction(path) as db:
            active = active_workflow(db)
        task = run_notes(goal, catalog, runtime, output, repair, first_diff_seed=742,
                         rapidocr=active == CANDIDATE, experience_db=path)
        if active == PARENT and task.get("experience_record_id"):
            cycle_id = str(uuid4())
            with transaction(path) as db:
                audit(db, cycle_id, "triggered", {"experience": task["experience_record_id"],
                                                  "budget": asdict(budget), "concurrency": 1})

            def trial(stage):
                return run_notes(synthetic_goal, catalog, runtime, output / "evolution" / stage, repair,
                                 first_diff_seed=742, rapidocr=True, experience_db=path, origin=stage)

            with ThreadPoolExecutor(max_workers=1) as executor:
                task["evolution"] = executor.submit(evolve, path, cycle_id, budget, task, trial).result()
            write_report(output, task)
        return task
