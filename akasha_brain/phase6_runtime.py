"""Exécution Notes et suivi durable dans une session d'évolution intégrée."""

from dataclasses import asdict
import json
from pathlib import Path
import secrets
from time import monotonic
from uuid import UUID

from bench.run_guided_repair import execution_limits, write_report
from bench.run_phase5_notes_action_selection import PROTOCOL, isolated_notes_sandbox, run_arm
from bench.run_phase5_notes_monitor import CASE
from bench.run_phase6_notes_evolution import APPROVED_PLANS, observe_trial, stage_bench

from . import memory_workflows
from .bounded_evolution import BoundedEvolution, Observation, Policy, SandboxScope
from .experience import transaction
from .integrated_evolution import IntegratedEvolution
from .memory import NotesMemory
from .memory_policy import PolicyWorkflowLibrary
from .notes_evolution import GOAL_FILE, lease
from .notes_link_promotion import KEY_FORMAT, NAMESPACE, canonical, digest, ssh_keygen
from .notes_sandbox import active_sandboxes, read_profile
from .phase6_skill import DESKTOP, GENERATION, REUSE, execute
from .planning import ENVIRONMENT, compile_goal

FAMILIES = {
    "route": ("without_predictor", "with_predictor", CASE),
    "skill": (GENERATION, REUSE, DESKTOP),
    "memory": ("contextual", "filtered_similarity", "notes_ocr_nominal"),
}
MANIFEST = "phase6-session.json"


def sign_with_key(key: Path, document: dict) -> str:
    result = ssh_keygen(["-Y", "sign", "-f", str(key), "-n", NAMESPACE], canonical(document))
    if result.returncode != 0:
        raise RuntimeError("La signature locale de la décision a échoué.")
    return result.stdout.decode("ascii")


def install_session(root: Path, cycles: dict[str, BoundedEvolution], public_key: str) -> None:
    """Publie les identifiants publics de registres qualifiés dans leur propre dossier."""
    if not KEY_FORMAT.fullmatch(public_key) or set(cycles) != set(FAMILIES):
        raise ValueError("Registre intégré incomplet.")
    manifest = {"version": 1, "public_key": public_key, "cycles": {
        family: {"id": cycle.cycle, "policy": asdict(cycle.policy)}
        for family, cycle in cycles.items()
    }}
    queue = root / "maintenance.sqlite"
    queue.touch(exist_ok=False)
    with transaction(queue) as db:
        db.execute("""CREATE TABLE jobs (
            task TEXT PRIMARY KEY, outcome TEXT NOT NULL CHECK(outcome IN ('passed','failed')),
            receipt TEXT, state TEXT NOT NULL CHECK(state IN ('waiting','running','finished','failed','interrupted')),
            detail TEXT
        )""")
        db.execute("CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL CHECK(paused IN (0,1)))")
        db.execute("INSERT INTO preferences VALUES (1, 0)")
    with (root / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)


class Phase6Session:
    def __init__(self, root: Path, key: Path):
        self.root = root.resolve(strict=True)
        self.key = key.resolve(strict=True)
        self.queue = self._file("maintenance.sqlite")
        manifest = json.loads(self._file(MANIFEST).read_bytes())
        public_key = manifest["public_key"]
        if (manifest["version"] != 1 or not KEY_FORMAT.fullmatch(public_key)
                or set(manifest["cycles"]) != set(FAMILIES)):
            raise ValueError("Manifeste de session d'évolution invalide.")
        result = ssh_keygen(["-y", "-f", str(self.key)], b"")
        if result.returncode != 0 or " ".join(result.stdout.decode("ascii").split()[:2]) != public_key:
            raise ValueError("La clé locale ne correspond pas à la session d'évolution.")
        cycles = {}
        for family, (parent, candidate, case) in FAMILIES.items():
            frozen = manifest["cycles"][family]
            policy = Policy(**frozen["policy"])
            if (policy.family, policy.parent, policy.candidate, policy.limited) != (family, parent, candidate, case):
                raise ValueError("Politique de session hors du périmètre Notes qualifié.")
            cycles[family] = BoundedEvolution(self._file(f"{family}.sqlite"), str(UUID(frozen["id"])), policy, public_key)
        self.coordinator = IntegratedEvolution(self._file("integrated.sqlite"), cycles)
        self.coordinator.status()
        self.memory = NotesMemory(self._file("journal.sqlite"))

    def _file(self, name: str) -> Path:
        path = (self.root / name).resolve(strict=True)
        if path.parent != self.root or not path.is_file():
            raise ValueError("Fichier de session hors périmètre.")
        return path

    def status(self) -> dict:
        state = self.coordinator.status()
        with transaction(self.queue) as db:
            state["jobs"] = dict(db.execute("SELECT state, count(*) FROM jobs GROUP BY state"))
            state["paused"] = bool(db.execute("SELECT paused FROM preferences WHERE id=1").fetchone()[0])
        return state

    def set_paused(self, paused: bool) -> None:
        with transaction(self.queue) as db:
            db.execute("UPDATE preferences SET paused = ? WHERE id=1", (int(paused),))

    def sign(self, document: dict) -> str:
        return sign_with_key(self.key, document)

    def request_rollback(self) -> dict:
        with lease(self.queue):
            self.coordinator.request_rollback(self.sign)
            return self.status()

    def run_task(self, goal, catalog, runtime, output, repair, budget, *, progress=None):
        if goal != json.loads(GOAL_FILE.read_bytes()) or repair is None or repair.backend != "cpu":
            raise PermissionError("Cette session est réservée au GoalSpec Notes synthétique et à Rbitnet CPU.")
        with lease(self.queue):
            selected = self.coordinator.status()["effective"]
            graph = compile_goal(goal, catalog, rbitnet=True, rapidocr=True)
            comparable = digest({"inputs": memory_workflows.trial_files(runtime=runtime),
                                 "plan": memory_workflows.plan_contract(graph)})
            library = PolicyWorkflowLibrary(self.memory, selected["memory"])
            route = selected["skill"]
            _, receipt, _, report = execute(
                library, goal, catalog, runtime, output, repair, DESKTOP, route, comparable,
                lambda scope: self.coordinator.select("skill", scope, DESKTOP) == route, None,
                cpu_threads=budget.cpu_threads, model_ram_mib=budget.model_ram_mb, progress=progress, keep_report=True,
            )
            report = {**report, "phase6_execution": {"skill": route, "memory": selected["memory"]}}
            write_report(output, report)
        return report, receipt

    def enqueue(self, task: str, outcome: str, receipt: Observation | None) -> None:
        UUID(task)
        payload = canonical(asdict(receipt)).decode() if receipt is not None else None
        with transaction(self.queue) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT outcome, receipt FROM jobs WHERE task = ?", (task,)).fetchone()
            if previous:
                if previous != (outcome, payload):
                    raise RuntimeError("Les preuves d’une tâche terminée ont changé.")
                return
            db.execute("INSERT INTO jobs VALUES (?, ?, ?, 'waiting', NULL)", (task, outcome, payload))

    def pending(self) -> list[str]:
        with transaction(self.queue) as db:
            return [row[0] for row in db.execute("SELECT task FROM jobs WHERE state = 'waiting' ORDER BY rowid")]

    def recover(self) -> None:
        with lease(self.queue):
            if not active_sandboxes():
                with transaction(self.queue) as db:
                    db.execute("""UPDATE jobs SET state = 'interrupted', detail = ? WHERE state = 'running'""",
                               (json.dumps({"reason": "process_interrupted"}),))

    def job(self, task: str) -> dict:
        with transaction(self.queue) as db:
            state, detail = db.execute("SELECT state, detail FROM jobs WHERE task = ?", (task,)).fetchone()
        return {"state": state, "detail": json.loads(detail) if detail else None}

    def maintain(self, task: str, runtime: Path, directory: Path, budget) -> dict:
        with lease(self.queue):
            with transaction(self.queue) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT state, receipt FROM jobs WHERE task = ?", (task,)).fetchone()
                if row is None or row[0] != "waiting":
                    return {"state": row[0] if row else "missing"}
                if db.execute("SELECT paused FROM preferences WHERE id=1").fetchone()[0]:
                    return {"state": "waiting", "detail": {"reason": "paused"}}
                if budget.max_trials < 1 or budget.wall_s <= 0:
                    detail = {"reason": "resource_budget_exceeded"}
                    db.execute("UPDATE jobs SET detail = ? WHERE task = ?", (json.dumps(detail), task))
                    return {"state": "waiting", "detail": detail}
                db.execute("UPDATE jobs SET state = 'running' WHERE task = ?", (task,))
            detail = {}
            try:
                if row[1] is not None:
                    receipt = Observation(**json.loads(row[1]))
                    scope = SandboxScope(receipt.sandbox_id, ENVIRONMENT, "R1", True, True)
                    detail["skill"] = self.coordinator.observe("skill", scope, receipt, self.sign)
                if self.coordinator.status()["autonomy_phase"] == 6:
                    with execution_limits(monotonic() + budget.wall_s, budget.cpu_threads, budget.model_ram_mb):
                        detail["route"] = self.observe_route(runtime, directory / task / "phase6-route")
                detail["effective"] = self.coordinator.status()
                state = "finished"
            except Exception as error:
                detail["error"] = type(error).__name__
                state = "failed"
                raise
            finally:
                with transaction(self.queue) as db:
                    db.execute("UPDATE jobs SET state = ?, detail = ? WHERE task = ?", (state, json.dumps(detail), task))
            return {"state": state, "detail": detail}

    def observe_route(self, runtime: Path, output: Path, *, store: str = "reference") -> dict:
        protocol = json.loads(PROTOCOL.read_bytes())
        if protocol["plans"] != APPROVED_PLANS:
            raise RuntimeError("Catalogue Notes différent du périmètre déclaré.")
        case, = (candidate for candidate in protocol["cases"] if candidate["id"] == CASE)
        output.mkdir(parents=True)
        stage = output / "input"
        stage_bench(stage, runtime)
        tag = secrets.token_hex(4)
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        report = {"sandbox": {}, "observation": {}, "trial": {}}

        def persist():
            write_report(output, report)

        with isolated_notes_sandbox(stage, tag, read_profile(), report["sandbox"], persist) as (sandbox, mount):
            scope = SandboxScope(sandbox, ENVIRONMENT, "R1", True, True)
            version = self.coordinator.select("route", scope, CASE)
            report["selected"] = version
            run_arm(sandbox, fr"{mount}\{store}", case, protocol["plans"], version, report["trial"], persist)
            receipt = observe_trial(sandbox, case, version, report["trial"])
        report["mismatches"] = list(receipt.mismatches)
        report["observation"] = self.coordinator.observe("route", scope, receipt, self.sign)
        persist()
        return {"selected": version, "mismatches": report["mismatches"], "observation": report["observation"]}
