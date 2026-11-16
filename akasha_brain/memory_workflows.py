"""Bibliothèque locale des workflows Notes et rejeu dans un bac dédié."""

from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from uuid import uuid4

from bench.run_guided_repair import BENCH, CHECKPOINTS, file_hash

from .memory import NOTES_SCOPE, NotesMemory, canonical_id, read
from .memory_scratch import remove_run, run_folder, scratch_lease
from .memory_store import MemoryRefusal, encode
from .notes_desktop import load_desktop_protocol
from .notes_evolution import CANDIDATE, GOAL_FILE, PARENT, evidence
from .notes_runtime import run_notes
from .notes_sandbox import active_sandboxes, read_profile
from .planning import PlanningError, compile_goal, load_catalog
from .project_backup import publish as publish_json
from .retention import load_policy

PARENT_REVISION = "1.0.0"
REUSE_REVISION = "1.1.0"
DIRECTORY = {
    PARENT_REVISION: {"parent": None, "default_graph": PARENT, "memory_enabled": False, "graphs": [PARENT]},
    REUSE_REVISION: {"parent": PARENT_REVISION, "default_graph": PARENT, "memory_enabled": True,
                     "graphs": [PARENT, CANDIDATE]},
}
COMMON_TERMS = "notes sauvegarde correction persistance sqlite note"
TERMS = {PARENT: f"{COMMON_TERMS} code tests",
         CANDIDATE: f"{COMMON_TERMS} relance bureau redémarrage ocr"}
FIXTURE_FILES = ("conftest.py", "notes_app.py", "tests/test_notes.py", "verifiers/verify_notes.py")
HARNESS_FILES = ("validate_guided_notes.ps1", "probe_notes_isolation.ps1", "probe_guest_channels.ps1")
DENIED_CONTROLS = {"missing_confinement": "permission_denied", "out_of_scope": "permission_denied"}
HIDDEN = {"erasure_requested", "retention_expired", "missing_object", "redacted_by_deletion"}


def plan_contract(plan: dict) -> dict:
    return {name: value for name, value in plan.items() if name != "goal_id"}


def text_hash(path: Path) -> str:
    return sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def trial_files(*, runtime: Path, staging: Path | None = None) -> dict:
    python = (staging / "python") if staging else runtime
    notes = BENCH / "notes"
    source = staging / "control" / "notes_store.py" if staging else notes / "notes_store.py"
    files = {"notes_store.py": source}
    files.update({name: (staging / "fixture" if staging else notes) / name for name in FIXTURE_FILES})
    files.update({name: (staging if staging else BENCH / "harness") / name for name in HARNESS_FILES})
    protocol = load_desktop_protocol({})
    return {"text": {name: text_hash(path) for name, path in files.items()},
            "runtime": {name: file_hash(python / name) for name in protocol["python_sha256"]},
            "protocol": protocol["version"]}


@dataclass(frozen=True)
class ObservedContext:
    files: dict
    isolated_runtime_available: bool
    ocr_available: bool
    desktop_requested: bool


def observe(runtime: Path, desktop: bool) -> ObservedContext:
    read_profile()
    available = not active_sandboxes()
    protocol = load_desktop_protocol({})
    try:
        ocr = all(version(package) == expected for package, expected in protocol["ocr"]["packages"].items())
    except PackageNotFoundError:
        ocr = False
    return ObservedContext(trial_files(runtime=runtime), available, ocr, desktop)


def words(value: str) -> set[str]:
    return set(re.findall(r"\w+", value.casefold()))


def relevance(query: set[str], indexed: set[str]) -> float:
    return len(query & indexed) / len(query | indexed) if query or indexed else 0.0


def graph_scores(candidates: list[dict], steps_by_index: dict) -> dict:
    if not candidates:
        return {}
    links = defaultdict(set)
    for index, steps in steps_by_index.items():
        capabilities = {step["id"]: (step["capability_id"], step["version"]) for step in steps}
        for step in steps:
            node = capabilities[step["id"]]
            links[index].add(node)
            links[node].add(index)
            for dependency in step["depends_on"]:
                parent = capabilities[dependency]
                links[node].add(parent)
                links[parent].add(node)
    weights = {row["index"]: row["signals"]["relevance"] + 0.05 for row in candidates}
    total = sum(weights.values())
    restart = {node: weights.get(node, 0.0) / total for node in links}
    scores = restart
    for _ in range(20):
        updated = {node: 0.2 * restart[node] for node in links}
        for node, neighbors in links.items():
            share = 0.8 * scores[node] / len(neighbors)
            for neighbor in sorted(neighbors, key=str):
                updated[neighbor] += share
        scores = updated
    return {index: scores[index] for index in weights}


def measured_outcome(report: dict) -> dict:
    steps = {step["id"]: step for step in report["trace"]}
    apply = steps.get("generate_diff", {}).get("result", {})
    validation = steps.get("verify", {}).get("result", {})
    desktop = steps.get("verify_desktop", {}).get("result", {})
    return {
        "status": report["status"],
        "steps": [{field: step.get(field) for field in ("id", "status", "authorization")} for step in report["trace"]],
        "diff_applied": apply.get("diff_applied"),
        "diff_sha256": apply.get("diff_sha256"),
        "git_apply_check": apply.get("git_apply_check"),
        "guest_sha256_verified": apply.get("guest_sha256_verified"),
        "tests": validation.get("tests"),
        "sqlite": validation.get("sqlite_verifier_exit"),
        "desktop": desktop.get("desktop"),
        "isolation": report.get("isolation"),
        "authorizations": report.get("authorization_controls"),
        "sandbox_stopped": report.get("sandbox_stopped"),
    }


class WorkflowLibrary:
    def __init__(self, memory: NotesMemory):
        self.memory = memory
        self.directory = memory.path.with_name(f"{memory.path.name}.registry")
        self.scratch = memory.path.with_name(f"{memory.path.name}.scratch")

    def install(self) -> None:
        with self.memory.access() as (control, db):
            for revision, document in DIRECTORY.items():
                path = self.directory / revision / "manifest.json"
                if path.resolve() != path:
                    raise MemoryRefusal("registry_unverified", "Emplacement d'annuaire invalide.")
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    publish_json(path, {"version": revision, **document})
                self.manifest(revision)
            control.execute("""CREATE TABLE IF NOT EXISTS memory_workflow_registry (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1), revision TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
            )""")
            control.execute("INSERT OR IGNORE INTO memory_workflow_registry VALUES (1, ?, 1)", (REUSE_REVISION,))
            control.execute("""CREATE TABLE IF NOT EXISTS memory_skill_state (
                workflow TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                successes INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS memory_scratch (
                run TEXT NOT NULL, source TEXT NOT NULL REFERENCES memory_items(id), PRIMARY KEY (run, source)
            )""")

    def manifest(self, version_id: str) -> dict:
        if version_id not in DIRECTORY:
            raise MemoryRefusal("registry_unverified", "Version d'annuaire inconnue.")
        path = self.directory / version_id / "manifest.json"
        if path.resolve() != path or not path.is_file():
            raise MemoryRefusal("registry_unverified", "Annuaire local indisponible.")
        try:
            observed = json.loads(path.read_bytes())
        except (OSError, ValueError) as error:
            raise MemoryRefusal("registry_unverified", "Annuaire local illisible.") from error
        if observed != {"version": version_id, **DIRECTORY[version_id]}:
            raise MemoryRefusal("registry_unverified", "Manifestes de l'annuaire différents de la version installée.")
        return observed

    def active(self, control) -> dict:
        if not control.execute("SELECT 1 FROM sqlite_schema WHERE name = 'memory_workflow_registry'").fetchone():
            raise MemoryRefusal("registry_unverified", "Annuaire local à initialiser.")
        row = control.execute("SELECT revision, enabled FROM memory_workflow_registry WHERE singleton = 1").fetchone()
        if row is None:
            raise MemoryRefusal("registry_unverified", "Version active introuvable.")
        manifest = self.manifest(row[0])
        if manifest["memory_enabled"] != bool(row["enabled"]):
            raise MemoryRefusal("registry_unverified", "L'état de la mémoire diffère de l'annuaire.")
        return manifest

    def rollback(self) -> dict:
        with self.memory.access() as (control, _):
            active = self.active(control)
            if active["parent"] is not None:
                parent = self.manifest(active["parent"])
                control.execute("UPDATE memory_workflow_registry SET revision = ?, enabled = ? WHERE singleton = 1",
                                (parent["version"], parent["memory_enabled"]))
            return self.active(control)

    def skill_state(self, control, workflow: str):
        row = control.execute("SELECT state, attempts, successes FROM memory_skill_state WHERE workflow = ?",
                              (workflow,)).fetchone()
        if row is None:
            raise MemoryRefusal("registry_unverified", "État de la compétence indisponible.")
        return row

    def active_for_graph(self, control, db, graph: str, revision: str, now, policy) -> bool:
        for row in db.execute("""SELECT id FROM memory_items WHERE scope = ? AND kind = 'workflow'
                AND json_extract(payload, '$.graph.graph_id') = ? AND json_extract(payload, '$.revision') = ?""",
                              (NOTES_SCOPE, graph, revision)):
            try:
                self.memory.require(control, db, row["id"], scope=NOTES_SCOPE, now=now, policy=policy)
            except MemoryRefusal as error:
                if error.code not in HIDDEN:
                    raise
            else:
                if self.skill_state(control, row["id"])["state"] == "active":
                    return True
        return False

    def transition(self, workflow: str, action: str) -> dict:
        expected, target = {"deprecate": ("active", "deprecated"), "retire": ("deprecated", "retired"),
                            "reactivate": ("deprecated", "active")}[action]
        with self.memory.access() as (control, db):
            self.memory.require_enabled(control)
            now, policy = self.memory.clock(), load_policy()
            recipe = read(self.memory, control, db, workflow, "workflow", now, policy)
            previous = self.skill_state(control, workflow)
            if previous["state"] != expected:
                raise MemoryRefusal("invalid_transition", "Transition de compétence non autorisée.")
            if target == "active" and self.active_for_graph(control, db, recipe["graph"]["graph_id"],
                                                            recipe["revision"], now, policy):
                raise MemoryRefusal("already_published", "Un workflow actif existe déjà pour ce graphe.")
            control.execute("UPDATE memory_skill_state SET state = ? WHERE workflow = ?", (target, workflow))
            return {"state": target, "attempts": previous["attempts"], "successes": previous["successes"]}

    def publish(self, reports: list[Path]) -> dict:
        goal = json.loads(GOAL_FILE.read_bytes())
        catalog = load_catalog()
        protocols = load_desktop_protocol({})
        if len(reports) < 2:
            raise MemoryRefusal("missing_evidence", "Deux exécutions réussies distinctes sont requises.")
        graph = None
        inputs = None
        proof_ids = []
        patch = None
        sandbox_ids = set()
        for path in reports:
            report = json.loads(path.read_bytes())
            graph_id = report["graph"]["graph_id"]
            if graph_id not in (PARENT, CANDIDATE):
                raise MemoryRefusal("out_of_scope", "Seuls les graphes Notes évalués sont admissibles.")
            expected = compile_goal(goal, catalog, rbitnet=True, rapidocr=graph_id == CANDIDATE)
            outcome = evidence(report, desktop=graph_id == CANDIDATE)
            files = trial_files(runtime=path.parent / "input/python", staging=path.parent / "input")
            raw = (path.parent / "rbitnet-1/proposal.diff").read_bytes()
            if (not outcome["verified"] or plan_contract(report["graph"]) != plan_contract(expected)
                    or report["authorization_controls"] != DENIED_CONTROLS
                    or report["repair"]["backend"] != "cpu" or report["repair"]["hashes"] != CHECKPOINTS
                    or not outcome["diff"] == sha256(raw).hexdigest() == protocols["diff_sha256"]
                    or files["text"]["notes_store.py"] != protocols["inputs_sha256"]["control/notes_store.py"]
                    or files["runtime"] != protocols["python_sha256"]
                    or report["sandbox_id"] in sandbox_ids
                    or outcome["experience"] in proof_ids
                    or (graph is not None and (graph != expected or inputs != files))):
                raise MemoryRefusal("invalid_evidence", "Preuves ou entrées incompatibles avec le workflow évalué.")
            graph, inputs, patch = expected, files, raw
            proof_ids.append(canonical_id(outcome["experience"]))
            sandbox_ids.add(canonical_id(report["sandbox_id"]))

        policy = load_policy()
        with self.memory.access() as (control, db):
            active = self.active(control)
            if not active["memory_enabled"]:
                raise MemoryRefusal("memory_disabled", "La mémoire est désactivée.")
            now = self.memory.clock()
            for item in proof_ids:
                source = read(self.memory, control, db, item, "experience", now, policy)
                if source["graph_id"] != graph["graph_id"] or source["record"]["verification"]["status"] != "pass":
                    raise MemoryRefusal("invalid_evidence", "Les preuves du journal ne correspondent pas au workflow.")
            if self.active_for_graph(control, db, graph["graph_id"], active["version"], now, policy):
                raise MemoryRefusal("already_published", "L'annuaire contient déjà un workflow actif pour ce graphe.")
            fields = {"control": control, "db": db, "scope": NOTES_SCOPE, "now": now, "policy": policy}
            artifact = self.memory.save(**fields, kind="artifact",
                                        payload={"diff": patch.decode("utf-8"), "sha256": sha256(patch).hexdigest()},
                                        parents=proof_ids)
            skill = self.memory.save(**fields, kind="skill", payload={"action": "apply_validated_notes_diff",
                                     "contract": plan_contract(graph)}, parents=proof_ids)
            workflow = self.memory.save(**fields, kind="workflow", parents=(artifact, skill),
                                        payload={"graph": plan_contract(graph), "inputs": inputs, "artifact": artifact,
                                                 "proofs": len(proof_ids), "revision": active["version"]})
            control.execute("INSERT INTO memory_skill_state (workflow, state) VALUES (?, 'candidate')", (workflow,))
            index = self.memory.save(**fields, kind="index", parents=(workflow,),
                                     payload={"workflow": workflow, "terms": TERMS[graph["graph_id"]]})
            control.execute("UPDATE memory_skill_state SET state = 'active' WHERE workflow = ?", (workflow,))
        return {"workflow": workflow, "index": index, "graph": graph["graph_id"], "proofs": len(proof_ids)}

    def candidates(self, control, db, active: dict, goal: dict, catalog: dict, context: ObservedContext,
                   *, replay_index: str | None = None) -> list[dict]:
        query = words(goal["user_intent"])
        policy = load_policy()
        now = self.memory.clock()
        result = []
        steps_by_index = {}
        for row in db.execute("SELECT id, created_at FROM memory_items WHERE scope = ? AND kind = 'index' ORDER BY id",
                              (NOTES_SCOPE,)):
            try:
                indexed = read(self.memory, control, db, row["id"], "index", now, policy)
                workflow = read(self.memory, control, db, indexed["workflow"], "workflow", now, policy)
            except MemoryRefusal as error:
                if error.code not in HIDDEN:
                    raise
                continue
            graph = workflow["graph"]
            if workflow["revision"] != active["version"] or graph["graph_id"] not in active["graphs"]:
                continue
            history = self.skill_state(control, indexed["workflow"])
            if history["state"] != "active" and replay_index != row["id"]:
                continue
            desktop = graph["graph_id"] == CANDIDATE
            reasons = []
            try:
                current = compile_goal(goal, catalog, rbitnet=True, rapidocr=desktop)
                if plan_contract(current) != graph:
                    reasons.append("graph_changed")
            except PlanningError as error:
                reasons.append(error.error.code.value)
            if desktop != context.desktop_requested:
                reasons.append("desktop_scope")
            if desktop and not context.ocr_available:
                reasons.append("ocr_unavailable")
            if not context.isolated_runtime_available:
                reasons.append("sandbox_unavailable")
            if workflow["inputs"] != context.files:
                reasons.append("inputs_changed")
            age = max(0.0, (now - datetime.fromisoformat(row["created_at"])).total_seconds())
            signals = {
                "relevance": relevance(query, words(indexed["terms"])),
                "recency": 2 ** (-age / (30 * 86400)),
                "importance": (history["successes"] / history["attempts"] if history["attempts"] else
                               min(workflow["proofs"] / 3, 1)),
            }
            steps_by_index[row["id"]] = graph["steps"]
            result.append({"index": row["id"], "graph": graph["graph_id"], "signals": signals,
                           "refusals": reasons, "workflow": indexed["workflow"]})
        eligible = [entry for entry in result if not entry["refusals"]]
        graph = graph_scores(eligible, {entry["index"]: steps_by_index[entry["index"]] for entry in eligible})
        for entry in result:
            signals = entry["signals"]
            signals["graph"] = graph.get(entry["index"], 0.0)
            entry["score"] = (0.65 * signals["relevance"] + 0.15 * signals["recency"] +
                              0.15 * signals["importance"] + 0.05 * signals["graph"])
        return result

    def compare(self, goal: dict, catalog: dict, context: ObservedContext) -> dict:
        """Compare les deux classements sur le même catalogue. Le bras similarité ne sert qu'à la mesure."""
        with self.memory.access() as (control, db):
            active = self.active(control)
            candidates = self.candidates(control, db, active, goal, catalog, context) if active["memory_enabled"] else []
        similar = max(candidates, key=lambda row: (row["signals"]["relevance"], row["graph"]), default=None)
        same_ranker = max((row for row in candidates if not row["refusals"]),
                          key=lambda row: (row["signals"]["relevance"], row["graph"]), default=None)
        gated = max((row for row in candidates if not row["refusals"]),
                    key=lambda row: (row["score"], row["graph"]), default=None)
        return {"similarity": similar, "filtered_similarity": same_ranker, "gated": gated, "candidates": candidates}

    def run(self, goal: dict, runtime: Path, *, desktop: bool, trace_id: str | None = None) -> dict:
        began = perf_counter()
        folder = run_folder(self.memory, str(uuid4()))
        with scratch_lease(folder):
            return self.run_leased(goal, runtime, desktop, trace_id, folder, began)

    def run_leased(self, goal, runtime, desktop, trace_id, folder, began):
        catalog = load_catalog()
        context = observe(runtime, desktop)
        policy = load_policy()
        run_id = folder.name
        with self.memory.access() as (control, db):
            active = self.active(control)
            if not active["memory_enabled"]:
                raise MemoryRefusal("memory_disabled", "La mémoire est désactivée. Le registre parent est actif.")
            expected = (read(self.memory, control, db, canonical_id(trace_id), "trace", self.memory.clock(), policy)
                        if trace_id else None)
            candidates = self.candidates(control, db, active, goal, catalog, context,
                                         replay_index=expected["index"] if expected else None)
            eligible = [entry for entry in candidates if not entry["refusals"]
                        and (expected is None or entry["index"] == expected["index"])]
            if not eligible:
                raise MemoryRefusal("preconditions_failed", "Aucun workflow ne satisfait les préconditions observées.")
            selected = max(eligible, key=lambda row: (row["score"], row["graph"]))
            now = self.memory.clock()
            recipe = read(self.memory, control, db, selected["workflow"], "workflow", now, policy)
            artifact = read(self.memory, control, db, recipe["artifact"], "artifact", now, policy)
            patch = artifact["diff"].encode("utf-8")
            if sha256(patch).hexdigest() != artifact["sha256"]:
                raise MemoryRefusal("artifact_unverified", "L'empreinte de l'artefact ne correspond plus.")
            parents = (selected["index"], trace_id) if trace_id else (selected["index"],)
            db.executemany("INSERT INTO memory_scratch VALUES (?, ?)", ((run_id, parent) for parent in parents))

        def checkpoint(staging=None):
            if staging and trial_files(runtime=runtime, staging=staging) != recipe["inputs"]:
                raise MemoryRefusal("preconditions_failed", "Les entrées préparées diffèrent de celles qualifiées.")
            with self.memory.access() as (control, db):
                if self.active(control) != active:
                    raise MemoryRefusal("memory_disabled", "La version active de l'annuaire a changé.")
                now = self.memory.clock()
                read(self.memory, control, db, selected["index"], "index", now, policy)
                if trace_id:
                    read(self.memory, control, db, trace_id, "trace", now, policy)
                elif self.skill_state(control, selected["workflow"])["state"] != "active":
                    raise MemoryRefusal("skill_inactive", "La compétence a quitté le registre actif.")

        report = None
        try:
            folder.mkdir(parents=True)
            report = run_notes(goal, catalog, runtime, folder / "run", rapidocr=desktop,
                               reused_diff=patch, check_reuse=checkpoint, origin="memory_reuse")
        finally:
            if report is not None and (not report.get("sandbox_id") or report.get("sandbox_stopped")):
                remove_run(folder)
                with self.memory.access() as (_, db):
                    db.execute("DELETE FROM memory_scratch WHERE run = ?", (run_id,))

        outcome = measured_outcome(report)
        if report["status"] != "passed":
            if trace_id is None:
                with self.memory.access() as (control, _):
                    control.execute("UPDATE memory_skill_state SET attempts = attempts + 1 WHERE workflow = ?",
                                    (selected["workflow"],))
            return {"status": "failed", "error": report.get("error"), "outcome": outcome}
        if expected is not None and outcome != expected["outcome"]:
            raise MemoryRefusal("replay_mismatch", "Le rejeu diffère du résultat observé précédemment.")
        with self.memory.access() as (control, db):
            if self.active(control) != active:
                raise MemoryRefusal("memory_disabled", "La version active de l'annuaire a changé.")
            if not trace_id and self.skill_state(control, selected["workflow"])["state"] != "active":
                raise MemoryRefusal("skill_inactive", "La compétence a quitté le registre actif.")
            generated = self.memory.save(control, db, kind="trace", scope=NOTES_SCOPE, now=self.memory.clock(),
                                         policy=policy, parents=parents,
                                         payload={"index": selected["index"], "outcome": outcome})
            if not trace_id:
                control.execute("""UPDATE memory_skill_state SET attempts = attempts + 1, successes = successes + 1
                                   WHERE workflow = ?""", (selected["workflow"],))
        return {"status": "passed", "trace": generated, "outcome": outcome, "selection": selected,
                "wall_s": round(perf_counter() - began, 3), "sandbox_wall_s": report["wall_s"]}


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    commands.add_parser("rollback")
    manage = commands.add_parser("skill")
    manage.add_argument("operation", choices=("deprecate", "retire", "reactivate"))
    manage.add_argument("workflow")
    publish = commands.add_parser("publish")
    publish.add_argument("reports", type=Path, nargs="+")
    run = commands.add_parser("run")
    run.add_argument("--goal", type=Path, default=GOAL_FILE)
    run.add_argument("--runtime", required=True, type=Path)
    run.add_argument("--desktop", action="store_true")
    run.add_argument("--trace")
    args = parser.parse_args()
    library = WorkflowLibrary(NotesMemory(args.db))
    try:
        if args.action == "init":
            library.install()
        if args.action == "publish":
            result = library.publish(args.reports)
        elif args.action == "rollback":
            result = library.rollback()
        elif args.action == "skill":
            result = library.transition(canonical_id(args.workflow), args.operation)
        elif args.action == "run":
            result = library.run(json.loads(args.goal.read_bytes()), args.runtime,
                                 desktop=args.desktop, trace_id=args.trace)
        else:
            with library.memory.access() as (control, _):
                result = library.active(control)
    except (MemoryRefusal, PlanningError) as error:
        print(encode({"status": "refused", "code": getattr(error, "code", "contract_refused")}))
        return 1
    except (OSError, KeyError, RuntimeError, sqlite3.Error, ValueError):
        print(encode({"status": "refused", "code": "storage_or_input_unverified"}))
        return 1
    print(encode(result))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
