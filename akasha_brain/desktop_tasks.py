"""Plans, historique et exécution asynchrone pour l'interface desktop."""

from datetime import datetime, timezone
import json
from pathlib import Path
from queue import SimpleQueue
from threading import Thread
from uuid import uuid4

from .notes_evolution import EvolutionBudget, evolution_overview, initialize, run_managed
from .notes_repair import RbitnetPaths
from .notes_runtime import run_notes
from .planning import compile_goal, load_catalog

GOAL = Path(__file__).resolve().parents[1] / "contracts/examples/goal_notes_regression.json"

STEP_TITLES = {
    "localize": "Localiser la régression",
    "prepare_reference": "Préparer le correctif",
    "generate_diff": "Générer le diff",
    "verify": "Vérifier les tests et SQLite",
    "verify_desktop": "Vérifier après relance",
}
STATUSES = {"waiting": "En attente", "running": "En cours", "passed": "Réussi", "failed": "Échec"}


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


def test_counts(result: dict) -> tuple[int, int] | None:
    tests = result.get("tests")
    total = len(tests) if isinstance(tests, list) else tests
    passed = result.get("passed")
    if type(total) is int and type(passed) is int:
        return passed, total
    return None


def saved_tasks(directory: Path) -> list[tuple[Path, dict]]:
    records = []
    for task_file in directory.glob("*/task.json"):
        try:
            record = json.loads(task_file.read_bytes())
            report_path = task_file.parent / "result/report.json"
            if report_path.is_file():
                report = json.loads(report_path.read_bytes())
                record = {**record, **report} if record["status"] == "running" else {**report, **record}
            if not layers(record["graph"]):
                continue
            datetime.fromisoformat(record["created_at"])
            if record["status"] in STATUSES and isinstance(record["created_at"], str):
                records.append((task_file.parent, record))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(records, key=lambda record: record[1]["created_at"], reverse=True)


def save_task(folder: Path, record: dict) -> None:
    draft = folder / "task.tmp"
    draft.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    draft.replace(folder / "task.json")


class NotesTasks:
    def __init__(self, directory: Path, runtime: Path | None, repair: RbitnetPaths | None, rapidocr: bool,
                 *, evolution_db: Path | None = None):
        self.directory = directory
        self.runtime = runtime
        self.repair = repair
        self.rapidocr = rapidocr
        self.evolution_db = evolution_db
        self.catalog = load_catalog()
        self.goal = json.loads(GOAL.read_bytes())
        if self.evolution_db is None:
            self.plan = compile_goal(self.goal, self.catalog, rbitnet=repair is not None, rapidocr=rapidocr)
        else:
            if repair is None or rapidocr:
                raise ValueError("L’évolution Notes exige Rbitnet et choisit le graphe actif.")
            self.goal = initialize(self.evolution_db, self.catalog)
            self.read_evolution()
        self.updates = SimpleQueue()
        self.worker = None

    @property
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def read_evolution(self) -> dict:
        state = evolution_overview(self.evolution_db)
        self.plan = state["active"]
        return state

    def start(self) -> tuple[Path, dict]:
        if self.busy or self.runtime is None or not (self.runtime / "python.exe").is_file():
            raise RuntimeError("Le lanceur est occupé ou le dossier Python portable est incomplet.")
        run_id = str(uuid4())
        if self.evolution_db is None:
            goal = {**self.goal, "goal_id": run_id}
        else:
            self.read_evolution()
            goal = self.goal
        folder = self.directory / run_id
        folder.mkdir(parents=True)
        record = {"created_at": datetime.now(timezone.utc).isoformat(), "graph": {**self.plan, "goal_id": goal["goal_id"]},
                  "status": "running", "trace": []}
        save_task(folder, record)
        self.worker = Thread(target=self.run, args=(folder, goal, record, self.runtime), name="Akasha Notes")
        self.worker.start()
        return folder, record

    def run(self, folder: Path, goal: dict, record: dict, runtime: Path) -> None:
        def progress(report):
            self.updates.put((folder, {**record, **report}))

        try:
            if self.evolution_db is None:
                report = run_notes(goal, self.catalog, runtime, folder / "result", self.repair,
                                   rapidocr=self.rapidocr, progress=progress)
            else:
                report = run_managed(goal, self.catalog, runtime, folder / "result", self.repair,
                                     self.evolution_db, EvolutionBudget(480, 3, 8, 8192), progress=progress)
        except Exception as error:
            report = {"status": "failed", "error": {"message": str(error)}}
        final = {**record, **report}
        try:
            save_task(folder, {key: final[key] for key in ("created_at", "graph", "status", "trace", "error") if key in final})
        except OSError:
            pass  # Le rapport du lanceur reste disponible.
        self.updates.put((folder, final))
