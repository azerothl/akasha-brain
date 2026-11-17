"""Accès MCP local au graphe Notes et à la préparation de projet."""

import argparse
from pathlib import Path
from queue import Empty
from threading import Lock
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .desktop_settings import app_directory, configured_runtime
from .desktop_tasks import NotesTasks, checked_task_diff, latest_steps, saved_task, test_counts
from .mcp_project import register_project_tools
from .notes_repair import RbitnetPaths
from .planning import PlanningError


def create_server(tasks: NotesTasks, *, project: Path | None = None) -> MCPServer:
    server = MCPServer(
        "Akasha Brain",
        instructions=("Inspectez le plan Notes et suivez le verdict par identifiant. "
                      "Pour un projet configuré, préparez un diff à examiner dans le desktop."),
    )
    start_lock = Lock()
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def drain_updates() -> None:
        # Les agents relisent le rapport durable, publié à chaque étape du graphe.
        while True:
            try:
                tasks.updates.get_nowait()
            except Empty:
                return

    @server.tool(annotations=read_only, structured_output=True)
    def notes_plan() -> dict[str, Any]:
        """Retourne le graphe Notes installé et indique si Python portable est disponible."""
        return {"graph": tasks.plan,
                "runtime_ready": tasks.runtime is not None and (tasks.runtime / "python.exe").is_file()}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=False, openWorldHint=False), structured_output=True)
    def notes_start() -> dict[str, str]:
        """Lance le graphe Notes synthétique dans Windows Sandbox et retourne un identifiant de suivi."""
        drain_updates()
        with start_lock:
            if tasks.busy:
                raise ToolError("Un essai Notes de ce serveur est déjà en cours.")
            if tasks.runtime is None or not (tasks.runtime / "python.exe").is_file():
                raise ToolError("Configurez Python portable dans le desktop ou au lancement du serveur.")
            try:
                folder, record = tasks.start()
            except (OSError, RuntimeError, PlanningError) as error:
                raise ToolError("Le banc Notes n’a pas pu être lancé.") from error
        return {"task_id": folder.name, "status": record["status"]}

    @server.tool(annotations=read_only, structured_output=True)
    def notes_status(task_id: UUID) -> dict[str, Any]:
        """Relit le verdict, les étapes, les tests, SQLite et le diff vérifié d’un essai Notes."""
        drain_updates()
        folder = tasks.directory / str(task_id)
        if folder.resolve() != folder or any(not (folder / name).resolve().is_relative_to(folder)
                                               for name in ("task.json", "result/report.json")):
            raise ToolError("Identifiant de tâche Notes inconnu.")
        record = saved_task(folder)
        if record is None:
            raise ToolError("Identifiant de tâche Notes inconnu.")
        trace = latest_steps(record)
        result = {"task_id": str(task_id), "status": record["status"],
                  "steps": [{"id": step["id"], "status": trace.get(step["id"], {}).get("status", "waiting")}
                            for step in record["graph"]["steps"]]}
        if record["status"] in ("passed", "failed"):
            result["wall_s"] = record.get("wall_s")
            result["sandbox_stopped"] = record.get("sandbox_stopped")
            verification = trace.get("verify", {}).get("result", {})
            if counts := test_counts(verification):
                result["tests"] = {"passed": counts[0], "total": counts[1]}
            if "sqlite_verdict" in verification:
                result["sqlite"] = verification["sqlite_verdict"]
            if desktop := trace.get("verify_desktop", {}).get("result", {}).get("desktop"):
                result["desktop"] = desktop
            if diff := checked_task_diff(folder, trace.get("generate_diff", {})):
                result["verified_diff"] = diff
            if record["status"] == "failed":
                result["error"] = (record.get("error") or {}).get("code", "execution_failed")
        return result

    if project is not None:
        register_project_tools(server, tasks, project)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-runtime", type=Path, help="Dossier Python portable du bac")
    parser.add_argument("--runs", type=Path, default=app_directory() / "agent-runs", help="Historique des essais MCP")
    parser.add_argument("--project", type=Path, help="Projet unique autorisé pour la préparation MCP")
    parser.add_argument("--rbitnet", type=Path, nargs=3, metavar=("BINAIRE", "GGUF", "TOKENIZER"),
                        help="Artefacts qualifiés de la réparation CPU")
    parser.add_argument("--rapidocr", action="store_true", help="Vérifier Notes après relance")
    args = parser.parse_args()
    if args.rapidocr and not args.rbitnet:
        parser.error("--rapidocr exige --rbitnet")
    runtime = args.python_runtime.resolve() if args.python_runtime else configured_runtime()
    repair = RbitnetPaths(*(path.resolve() for path in args.rbitnet)) if args.rbitnet else None
    tasks = NotesTasks(args.runs.resolve(), runtime, repair, args.rapidocr)
    try:
        server = create_server(tasks, project=args.project)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
