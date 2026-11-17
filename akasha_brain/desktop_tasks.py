"""Plans, historique et exécution asynchrone pour l'interface desktop."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from queue import SimpleQueue
from uuid import uuid4

from .desktop_jobs import DesktopJobs
from .notes_evolution import EvolutionBudget, evolution_overview, initialize, run_managed, run_project_cycle
from .notes_repair import RbitnetPaths
from .notes_runtime import run_notes
from .planning import compile_goal, load_catalog
from .specialist_registry import require_specialist

GOAL = Path(__file__).resolve().parents[1] / "contracts/examples/goal_notes_regression.json"
DEFAULT_EVOLUTION_BUDGET = EvolutionBudget(480, 3, 8, 8192)

STEP_TITLES = {
    "localize": "Localiser la régression",
    "prepare_reference": "Préparer le correctif",
    "generate_diff": "Générer le diff",
    "verify": "Vérifier les tests et SQLite",
    "verify_desktop": "Vérifier après relance",
}
STATUSES = {"waiting": "En attente", "running": "En cours", "passed": "Réussi", "failed": "Échec"}


def notes_specialists(plan: dict) -> dict:
    bindings = {
        "notes.repair_rbitnet": ("code", "unified-diff.v1", "rbitnet", 8192),
        "notes.verify": ("verification", "verified-state.v1", "python-sqlite", 0),
        "notes.verify_desktop": ("ocr", "ocr-text.v1", "rapidocr-onnxruntime", 4096),
    }
    routes = {}
    for step in plan["steps"]:
        capability = step["capability_id"]
        if capability in bindings:
            modality, contract, engine, ram_mib = bindings[capability]
            specialist = require_specialist(capability, modality, contract, engine, ram_mib=ram_mib)
            routes[capability] = specialist.evidence(capability)
    return routes


def layers(plan: dict) -> list[list[dict]]:
    """Range le DAG par profondeur en gardant l'ordre déclaré dans chaque rang."""
    steps = plan["steps"]
    remaining = {step["id"]: step for step in steps}
    if len(remaining) != len(steps):
        raise ValueError("Identifiants de nœuds dupliqués.")
    resolved = set()
    ordered = []
    while remaining:
        current = [step for step in remaining.values() if set(step["depends_on"]) <= resolved]
        if not current:
            raise ValueError("Dépendances du graphe incohérentes.")
        ordered.append(current)
        for step in current:
            resolved.add(step["id"])
            del remaining[step["id"]]
    return ordered


def latest_steps(report: dict) -> dict[str, dict]:
    return {row["id"]: row for row in report.get("trace", []) if row.get("status") in STATUSES}


def checked_task_diff(folder: Path, row: dict) -> str | None:
    result = row.get("result", {})
    attempt = row.get("attempt")
    if (row.get("id") != "generate_diff" or not isinstance(result, dict) or type(attempt) is not int or attempt < 1
            or result.get("guest_sha256_verified") is not True):
        return None
    relative = f"rbitnet-{attempt}/proposal.diff"
    if result.get("diff_file") != relative:
        return None
    try:
        folder = folder.resolve(strict=True)
        output = (folder / "result").resolve(strict=True)
        path = (output / relative).resolve(strict=True)
        if not (output.is_relative_to(folder) and path.is_relative_to(output)) or not path.is_file():
            return None
        with path.open("rb") as stream:
            payload = stream.read(64 * 1024 + 1)
        if len(payload) <= 64 * 1024 and sha256(payload).hexdigest() == result.get("diff_sha256"):
            return payload.decode("utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return None
    return None


def test_counts(result: dict) -> tuple[int, int] | None:
    tests = result.get("tests")
    total = len(tests) if isinstance(tests, list) else tests
    passed = result.get("passed")
    if type(total) is int and type(passed) is int:
        return passed, total
    return None


def saved_task(folder: Path) -> dict | None:
    try:
        record = json.loads((folder / "task.json").read_bytes())
        report_path = folder / "result/report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_bytes())
            record = {**record, **report} if record["status"] in ("waiting", "running") else {**report, **record}
        datetime.fromisoformat(record["created_at"])
        if record["status"] in STATUSES and layers(record["graph"]):
            return record
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def saved_tasks(directory: Path) -> list[tuple[Path, dict]]:
    records = [(task_file.parent, record) for task_file in directory.glob("*/task.json")
               if (record := saved_task(task_file.parent)) is not None]
    return sorted(records, key=lambda record: record[1]["created_at"], reverse=True)


def save_task(folder: Path, record: dict) -> None:
    draft = folder / "task.tmp"
    draft.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    draft.replace(folder / "task.json")


class NotesTasks:
    def __init__(self, directory: Path, runtime: Path | None, repair: RbitnetPaths | None, rapidocr: bool,
                 *, evolution_db: Path | None = None, evolution_budget: EvolutionBudget = DEFAULT_EVOLUTION_BUDGET,
                 integrated=None):
        self.directory = directory
        self.runtime = runtime
        self.repair = repair
        self.rapidocr = rapidocr
        self.evolution_db = evolution_db
        self.integrated = integrated
        self.evolution_budget = evolution_budget
        self.catalog = load_catalog()
        self.goal = json.loads(GOAL.read_bytes())
        if integrated is not None:
            if evolution_db is not None or repair is None or repair.backend != "cpu":
                raise ValueError("La session intégrée exige Rbitnet CPU et un seul registre d'évolution.")
            self.plan = compile_goal(self.goal, self.catalog, rbitnet=True, rapidocr=True)
            self.integrated_status = integrated.status()
            integrated.recover()
        elif self.evolution_db is None:
            self.plan = compile_goal(self.goal, self.catalog, rbitnet=repair is not None, rapidocr=rapidocr)
        else:
            if repair is None or rapidocr:
                raise ValueError("L’évolution Notes exige Rbitnet et choisit le graphe actif.")
            self.goal = initialize(self.evolution_db, self.catalog)
            self.read_evolution()
        self.updates = SimpleQueue()
        self.scheduler = DesktopJobs()
        self.execution = None
        if integrated is not None and runtime is not None:
            self.schedule_integrated(runtime)

    @property
    def busy(self) -> bool:
        return self.execution is not None and not self.execution.done()

    def read_evolution(self) -> dict:
        state = evolution_overview(self.evolution_db)
        self.plan = state["active"]
        return state

    def start(self) -> tuple[Path, dict]:
        if self.busy or self.runtime is None or not (self.runtime / "python.exe").is_file():
            raise RuntimeError("Le lanceur est occupé ou le dossier Python portable est incomplet.")
        run_id = str(uuid4())
        if self.integrated is not None:
            goal = self.goal
        elif self.evolution_db is None:
            goal = {**self.goal, "goal_id": run_id}
        else:
            self.read_evolution()
            goal = self.goal
        folder = self.directory / run_id
        folder.mkdir(parents=True)
        record = {"created_at": datetime.now(timezone.utc).isoformat(), "graph": {**self.plan, "goal_id": goal["goal_id"]},
                  "status": "waiting", "trace": []}
        save_task(folder, record)
        runtime = self.runtime
        self.execution = self.scheduler.submit(lambda: self.run(folder, goal, record, runtime))
        return folder, record

    def submit_project(self, operation):
        if self.evolution_db is None:
            return self.scheduler.submit(operation)
        runtime = self.runtime

        def maintain(outcome):
            return run_project_cycle(self.catalog, runtime, self.directory / "evolution", self.repair,
                                     self.evolution_db, self.evolution_budget, outcome,
                                     interactive=self.scheduler.checkpoint)

        def run():
            try:
                result = operation()
            except Exception:
                self.scheduler.submit(lambda: maintain("failed"), background=True)
                raise
            self.scheduler.submit(lambda: maintain("passed"), background=True)
            return result

        return self.scheduler.submit(run)

    def run(self, folder: Path, goal: dict, record: dict, runtime: Path) -> None:
        def progress(report):
            self.updates.put((folder, {**record, **report}))

        receipt = None
        try:
            routes = notes_specialists(record["graph"])
            if self.integrated is not None:
                report, receipt = self.integrated.run_task(goal, self.catalog, runtime, folder / "result", self.repair,
                                                           self.evolution_budget, progress=progress)
            elif self.evolution_db is None:
                report = run_notes(goal, self.catalog, runtime, folder / "result", self.repair,
                                   rapidocr=self.rapidocr, progress=progress)
            else:
                report = run_managed(goal, self.catalog, runtime, folder / "result", self.repair,
                                     self.evolution_db, self.evolution_budget, progress=progress,
                                     schedule_evolution=lambda work: self.scheduler.submit(work, background=True),
                                     interactive=self.scheduler.checkpoint)
            for row in report.get("trace", []):
                capability = row.get("capability_id")
                outcome = row.get("result", {})
                if capability in routes and outcome and not outcome.get("reused"):
                    if capability != "notes.repair_rbitnet" or outcome.get("residency"):
                        row["routing"] = routes[capability]
        except Exception as error:
            report = {"status": "failed", "error": {"message": str(error)}}
        final = {**record, **report}
        try:
            save_task(folder, {key: final[key] for key in ("created_at", "graph", "status", "trace", "error", "phase6_execution")
                               if key in final})
        except OSError:
            pass  # Le rapport du lanceur reste disponible.
        self.updates.put((folder, final))
        if self.integrated is not None:
            self.integrated.enqueue(folder.name, final["status"], receipt)
            self.schedule_integrated(runtime)

    def schedule_integrated(self, runtime: Path) -> None:
        self.integrated_status = self.integrated.status()
        if self.integrated_status["paused"]:
            return
        for task in self.integrated.pending():
            self.scheduler.submit(lambda task=task: self.maintain_integrated(task, runtime), background=True)

    def maintain_integrated(self, task: str, runtime: Path):
        try:
            return self.integrated.maintain(task, runtime, self.directory, self.evolution_budget)
        finally:
            self.integrated_status = self.integrated.status()
