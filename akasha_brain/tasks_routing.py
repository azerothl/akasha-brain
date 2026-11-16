"""Point d'entrée du routage SQL du banc Tâches."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory

from bench.harness.tasks_oracle_deltas import FILTERS
from bench.run_guided_repair import file_hash, write_report
from bench.run_phase4_tasks_reserved import LOCK, REFERENCE_LOCK, ROOT, freeze_document
from bench.run_phase4_tasks_specialist import RECHECK_TIMEOUT_S, run_case
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .experience import transaction
from .notes_evolution import audit
from .notes_repair import RbitnetPaths
from .planning import PlanningError, TASKS_ENVIRONMENT, TASKS_TARGET, compile_goal, load_catalog
from .tasks_sql_specialist_v2 import verify_coverage
from .tasks_sql_transfer import run as run_reference
from . import tasks_gate

QUALIFICATION = ROOT / "bench/results/phase4-tasks-reserved-v1.json"
REFERENCE = "tasks-rbitnet-sql@1.3.0"
SPECIALIST = "tasks-rbitnet-sql-structured@3.0.0"
REQUIRED_FILES = ("goal.json", "state.json", "schema.sql", "repair.py", "oracle.py")
OPTIONAL_FILES = ("board.py", "reference.py")
TRANSITIONS = {"activate": (("candidate",), "active"), "deprecate": (("active",), "deprecated"),
               "retire": (("active", "deprecated"), "retired")}


def qualification() -> dict:
    lock = json.loads(LOCK.read_bytes())
    proof = json.loads(QUALIFICATION.read_bytes())
    lock_sha = file_hash(LOCK)
    runs = [case["arms"]["v3"][-1] for case in proof["runs"].values()]
    if (lock != freeze_document() or proof["status"] != "passed" or proof["freeze_sha256"] != lock_sha
            or proof["graphs"] != {"reference": REFERENCE, "v3": SPECIALIST}
            or proof["evolution"] != "excluded" or proof["scores"]["v3"] != {"evaluated": 2, "first": 2, "final": 2}
            or len(runs) != 2 or len({run["sandbox_id"] for run in runs}) != 2):
        raise RuntimeError("La qualification du spécialiste Tâches ne correspond pas à son gel.")
    for run in runs:
        first = run["attempts"]["1"]
        checks = first["verification"]
        if (not run["evaluated"] or not run["sandbox_stopped"] or run["accepted_attempt"] != 1
                or run["evolution"] != "excluded" or not first["git_verified"]
                or first["coverage"]["status"] != "passed" or not checks["sqlite_unchanged"]
                or set(checks["filters"]) != set(FILTERS) or not all(checks["filters"].values())):
            raise RuntimeError("Une preuve indépendante du spécialiste est incomplète.")
    return {"freeze_sha256": lock_sha, "qualification_sha256": file_hash(QUALIFICATION)}


def tasks_scope(goal: dict) -> bool:
    return goal.get("inputs") == [TASKS_TARGET] and goal.get("constraints", {}).get("environment_id") == TASKS_ENVIRONMENT


def case_hashes(directory: Path) -> dict:
    return {name: file_hash(directory / name) for name in (*REQUIRED_FILES, *OPTIONAL_FILES)
            if name in REQUIRED_FILES or (directory / name).is_file()}


def bind_contract(directory: Path, target: str, plan: dict) -> dict:
    goal = json.loads((directory / "goal.json").read_bytes())
    if not tasks_scope(goal) or target not in FILTERS:
        raise ValueError("Une consigne Tâches et un filtre déclaré sont nécessaires.")
    if not isinstance(plan, dict) or set(plan) != {"where", "order"}:
        raise ValueError("Le contrat exige un plan structuré where et order.")
    verify_coverage(plan, plan)
    return {"version": 1, "target": target, "goal_id": goal["goal_id"],
            "intent_sha256": sha256(goal["user_intent"].encode()).hexdigest(),
            "case_sha256": case_hashes(directory), "plan": plan}


def compatible(directory: Path, contract: dict) -> bool:
    if not isinstance(contract, dict):
        return False
    known_schema = json.loads(LOCK.read_bytes())["files_sha256"]["bench/phase4_tasks_dev/schema.sql"]
    schema = (directory / "schema.sql").read_text(encoding="utf-8")
    # Le lanceur v3 lit le schéma avec SQLite sur l'hôte. Sa définition doit être celle du banc figé.
    if sha256(schema.encode()).hexdigest() != known_schema:
        return False
    try:
        return contract == bind_contract(directory, contract["target"], contract["plan"])
    except (KeyError, TypeError, ValueError):
        return False


def snapshot_case(source: Path, directory: Path) -> None:
    source = source.resolve(strict=True)
    for name in (*REQUIRED_FILES, *OPTIONAL_FILES):
        path = source / name
        if name in OPTIONAL_FILES and not path.exists():
            continue
        if path.resolve(strict=True).parent != source or not path.is_file():
            raise ValueError(f"Fichier de cas hors périmètre ({name}).")
        shutil.copyfile(path, directory / name)


class Registry:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> dict:
        proof = qualification()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE tasks_skill (singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                state TEXT NOT NULL CHECK (state IN ('candidate', 'active', 'deprecated', 'retired')),
                provenance TEXT NOT NULL)""")
            db.execute("CREATE TABLE evolution_events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)")
            for operation in ("UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER audit_{operation.lower()} BEFORE {operation} ON evolution_events
                               BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
            db.execute("INSERT INTO tasks_skill VALUES (1, 'candidate', ?)", (json.dumps(proof),))
            audit(db, SPECIALIST, "initialized", proof)
        return self.status()

    def _read(self, db) -> tuple[str, dict]:
        row = db.execute("SELECT state, provenance FROM tasks_skill WHERE singleton = 1").fetchone()
        if row is None:
            raise RuntimeError("Le registre Tâches n'est pas initialisé.")
        return row[0], json.loads(row[1])

    def status(self) -> dict:
        if not self.path.is_file():
            raise RuntimeError("Le registre Tâches est introuvable.")
        with transaction(self.path) as db:
            state, proof = self._read(db)
        return {"state": state, "specialist": SPECIALIST, "reference": REFERENCE, **proof}

    def transition(self, action: str) -> dict:
        self.status()
        allowed, target = TRANSITIONS[action]
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state, proof = self._read(db)
            if state not in allowed or (action == "activate" and qualification() != proof):
                raise RuntimeError("Transition ou qualification Tâches invalide.")
            db.execute("UPDATE tasks_skill SET state = ? WHERE singleton = 1", (target,))
            audit(db, SPECIALIST, action, {"from": state, "to": target})
        return self.status()

    def admit(self, goal: dict, directory: Path, contract: dict | None) -> dict:
        if not tasks_scope(goal):
            return {"graph": None, "reason": "outside_tasks"}
        self.status()
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state, proof = self._read(db)
            graph, reason = REFERENCE, state
            if state == "active":
                try:
                    qualified = qualification() == proof
                except (OSError, ValueError, RuntimeError, KeyError):
                    qualified = False
                if not qualified:
                    reason = "qualification_unavailable"
                elif contract is None or not compatible(directory, contract):
                    reason = "coverage_unavailable"
                else:
                    graph, reason = SPECIALIST, "qualified_coverage"
            decision = {"graph": graph, "reason": reason, "state": state}
            audit(db, SPECIALIST, "routed", {"goal_id": goal["goal_id"], **decision})
            return decision

    def record_gate(self, goal_id: str, inputs: dict, observed: dict, effective: str) -> None:
        with transaction(self.path) as db:
            audit(db, SPECIALIST, "gate_evaluated", {"goal_id": goal_id, "signals": inputs,
                                                   "decision": observed, "effective": effective})


def run(registry: Registry, case: Path, runtime: Path, output: Path, paths: RbitnetPaths,
        contract: dict | None = None, *, gate_request: Path | None = None) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="tasks-route-", dir=output.parent) as folder:
        staged = Path(folder)
        snapshot_case(case, staged)
        goal = json.loads((staged / "goal.json").read_bytes())
        compile_goal(goal, load_catalog(), rbitnet=True)
        if not tasks_scope(goal) or paths.backend != "cpu":
            raise ValueError("Le routage SQL exige un objectif du banc Tâches sur Rbitnet CPU.")
        decision = registry.admit(goal, staged, contract)
        gate = None
        if gate_request is not None:
            paths.verify()
            facts = tasks_gate.signals("specialist" if decision["graph"] == SPECIALIST else "reference")
            gate = tasks_gate.evaluate(runtime, gate_request, [facts], output.parent, samples=1)
            observed, = gate["decisions"]
            effective = observed["akasha_model"]
            if effective == "ready":
                compile_goal(goal, load_catalog(), rbitnet=True)
                if registry.admit(goal, staged, contract) != decision:
                    effective = "blocked"
            gate["effective"] = effective
            registry.record_gate(goal["goal_id"], facts, observed, effective)
            if effective != "ready":
                code = ErrorCode.NEEDS_CLARIFICATION if effective == "abstain" else ErrorCode.PERMISSION_DENIED
                error = AkashaError(code, "La porte Tâches n'a pas admis l'exécution.", {"decision": effective})
                report = {"status": "failed", "error": error.as_dict(), "route": decision, "gate": gate,
                          "evolution": "excluded"}
                output.mkdir()
                write_report(output, report)
                return report
        if decision["graph"] == SPECIALIST:
            (staged / "oracle.py").replace(staged / "independent_oracle.py")
            shutil.copyfile(Path(__file__).with_name("tasks_route_oracle.py"), staged / "oracle.py")
            (staged / "routing_target.json").write_text(json.dumps(contract["target"]), encoding="utf-8")
            report = run_case(staged, runtime, output, paths, timeout_s=RECHECK_TIMEOUT_S,
                              required=contract["plan"], v3=True)
        else:
            frozen = json.loads(REFERENCE_LOCK.read_bytes())
            report = run_reference(staged, frozen, runtime, output, paths, "cpu", None)
    report["route"] = decision
    if gate is not None:
        report["gate"] = gate
    write_report(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", *TRANSITIONS, "run"):
        command = commands.add_parser(name)
        command.add_argument("--registry", type=Path, required=True)
        if name == "run":
            for option in ("case", "runtime", "output", "coverage"):
                command.add_argument(f"--{option}", required=option != "coverage", type=Path)
            command.add_argument("--rbitnet", nargs=3, required=True, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
            command.add_argument("--gate-request", type=Path, help="Demande unitaire de la roue akasha-model vérifiée.")
    bind = commands.add_parser("bind")
    bind.add_argument("--case", required=True, type=Path)
    bind.add_argument("--plan", required=True, type=Path)
    bind.add_argument("--target", required=True, choices=FILTERS)
    bind.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "bind":
            result = bind_contract(args.case.resolve(), args.target, json.loads(args.plan.read_bytes()))
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        else:
            registry = Registry(args.registry.resolve())
            if args.command == "run":
                contract = json.loads(args.coverage.read_bytes()) if args.coverage else None
                paths = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet))
                result = run(registry, args.case.resolve(), args.runtime.resolve(strict=True), args.output.resolve(),
                             paths, contract, gate_request=args.gate_request.resolve() if args.gate_request else None)
            elif args.command == "init":
                result = registry.initialize()
            elif args.command == "status":
                result = registry.status()
            else:
                result = registry.transition(args.command)
    except PlanningError as exc:
        result = {"status": "failed", "error": exc.error.as_dict()}
    except (OSError, RuntimeError, ValueError, KeyError, sqlite3.Error) as exc:
        error = AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(exc))
        result = {"status": "failed", "error": error.as_dict()}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return int(result.get("status") == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
