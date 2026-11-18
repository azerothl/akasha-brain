"""Préparation et lecture de propositions sur le projet autorisé au serveur MCP."""

from collections.abc import Callable
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from typing import Any
from uuid import UUID, uuid4

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from bench.run_guided_repair import write_report
from contracts.akasha_contracts.errors import ErrorCode

from .desktop_tasks import NotesTasks
from .project import CODE_FILE_LIMIT, inspect_code, prepare, preview_replacement, project_file
from .project_common import ProjectError, digest, project_scope
from . import whisper_pilot
from .planning import PlanningError


def register_project_tools(server: MCPServer, tasks: NotesTasks, project: Path) -> None:
    project = project.resolve(strict=True)
    scope = project_scope(project)
    directory = (tasks.directory / "projects").resolve()
    if directory.is_relative_to(project):
        raise ValueError("Le dossier de propositions MCP doit être situé hors du projet autorisé.")
    lock = Lock()
    active = None
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def require_project() -> None:
        if project_scope(project) != scope:
            raise ToolError("Le dossier du projet autorisé a changé. Redémarrez le serveur avec le projet voulu.")

    def read_project(action: Callable[[], Any]) -> Any:
        try:
            require_project()
            return action()
        except (ProjectError, PlanningError) as error:
            raise ToolError(str(error)) from error
        except OSError as error:
            raise ToolError("Impossible de lire les fichiers du projet autorisé.") from error

    if whisper_pilot.configured():
        @server.tool(annotations=read_only, structured_output=True)
        async def audio_transcribe(file: str) -> dict[str, Any]:
            """Transcrit un WAV ou FLAC français du projet et marque les passages incertains par segment."""
            cancelled = Event()

            def checkpoint():
                if cancelled.is_set():
                    raise InterruptedError("Transcription annulée.")

            try:
                return await asyncio.to_thread(read_project, lambda: whisper_pilot.transcribe(project, file, checkpoint))
            finally:
                cancelled.set()

    def prepare_in_sandbox(folder: Path, target: str, replacement: bytes, test: str, runtime: Path,
                           inputs: tuple[str, ...]) -> None:
        with lock:
            write_report(folder, {"scope": scope, "status": "running"})
        try:
            require_project()
            with TemporaryDirectory(prefix="replacement-", dir=folder) as scratch:
                candidate = Path(scratch) / "candidate.txt"
                candidate.write_bytes(replacement)
                proposal = prepare(project, folder / "proposal", target, candidate, test, runtime,
                                   inputs=inputs, input_byte_limit=CODE_FILE_LIMIT)
        except ProjectError as error:
            detail = {"code": error.error.code.value, "message": error.error.message}
            if "guest_exit_code" in error.error.details:
                detail["guest_exit_code"] = error.error.details["guest_exit_code"]
            result = {"status": "failed", "error": detail}
        except (OSError, RuntimeError, ValueError, ToolError):
            result = {"status": "failed", "error": {"code": ErrorCode.ENVIRONMENT_OBSERVATION_FAILED.value,
                                                   "message": "La préparation dans Windows Sandbox a échoué."}}
        else:
            result = {key: proposal[key] for key in ("status", "validation", "wall_s")}
        with lock:
            write_report(folder, {"scope": scope, **result})

    @server.tool(annotations=read_only, structured_output=True)
    def project_inspect(file: str, first_line: int = 1, limit: int = 80) -> dict[str, Any]:
        """Lit une fenêtre de code UTF-8 dans un fichier relatif du projet autorisé."""
        return read_project(lambda: inspect_code(project, [file], first_line=first_line, limit=limit))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=False, openWorldHint=False), structured_output=True)
    def project_prepare(target: str, replacement: str, test: str, inputs: list[str] | None = None) -> dict[str, str]:
        """Teste un remplacement UTF-8 dans Windows Sandbox et renvoie son identifiant de suivi."""
        nonlocal active
        selected = tuple(inputs or ())
        try:
            content = replacement.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ToolError("Le remplacement doit être un texte UTF-8 valide.") from error
        if len(selected) > 30 or len(content) > CODE_FILE_LIMIT:
            raise ToolError("Limite de préparation dépassée pour les fichiers ou le texte du remplacement.")
        names = (target, test, *selected)
        if len({name.casefold() for name in names}) != len(names):
            raise ToolError("Le fichier cible, le test et les entrées doivent avoir des chemins distincts.")
        runtime = tasks.runtime
        if runtime is None or not (runtime / "python.exe").is_file():
            raise ToolError("Configurez le dossier Python portable pour préparer un projet.")
        with lock:
            if active is not None and not active.done():
                raise ToolError("Une préparation de projet est déjà en cours.")
            read_project(lambda: [project_file(project, name) for name in names])
            folder = directory / str(uuid4())
            try:
                folder.mkdir(parents=True)
                write_report(folder, {"scope": scope, "status": "waiting"})
            except OSError as error:
                raise ToolError("Impossible de créer le dossier de la proposition.") from error
            active = tasks.submit_project(lambda: prepare_in_sandbox(folder, target, content, test, runtime, selected))
        return {"proposal_id": folder.name, "status": "waiting"}

    @server.tool(annotations=read_only, structured_output=True)
    def project_status(proposal_id: UUID) -> dict[str, Any]:
        """Relit le verdict de préparation et le diff à examiner dans l’interface Windows."""
        folder = directory / str(proposal_id)
        proposal = folder / "proposal"

        def read() -> dict[str, Any]:
            names = ("report.json", "proposal/proposal.json", "proposal/proposal.diff")
            if folder.resolve() != folder or any(not (folder / name).resolve().is_relative_to(folder) for name in names):
                raise ToolError("Identifiant de proposition inconnu.")
            try:
                with lock:
                    record = json.loads((folder / "report.json").read_bytes())
            except (OSError, ValueError) as error:
                raise ToolError("Identifiant de proposition inconnu.") from error
            if record.pop("scope", None) != scope:
                raise ToolError("Identifiant de proposition inconnu.")
            if record["status"] == "awaiting_approval":
                review = preview_replacement(project, proposal)
                record.update(proposal_path=str(review.proposal), file=review.target, test=review.test,
                              verified_diff=review.diff, diff_sha256=digest(review.diff.encode("utf-8")),
                              approval_expires_at=review.approval_expires_at.isoformat())
            return {"proposal_id": str(proposal_id), **record}

        return read_project(read)
