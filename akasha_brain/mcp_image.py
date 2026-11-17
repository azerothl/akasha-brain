"""Génération d’images isolée et restitution du PNG dans la session MCP."""

from base64 import b64encode
from dataclasses import dataclass, field
from hashlib import sha256
import json
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID, uuid4

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from contracts.akasha_contracts.errors import ErrorCode

from .capability_recovery import Recovery
from .desktop_jobs import DesktopJobs
from .image_assets import DownloadReview
from .image_execution import MAX_PNG_BYTES
from .image_recovery import normalize_prompt
from .planning import PlanningError
from .project_common import ProjectError


@dataclass
class ImageJob:
    prompt: str | None
    report: dict[str, Any] = field(default_factory=lambda: {"status": "waiting"})
    png: bytes | None = None


def register_image_tools(server: MCPServer, scheduler: DesktopJobs, runs: Path,
                         runtime: Path | None, project: Path | None) -> None:
    recovery = Recovery(runs.resolve() / "capability-recovery.sqlite", runtime, lambda _: None, lambda: False)
    jobs: dict[UUID, ImageJob] = {}
    lock = Lock()
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    enqueue = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    def find(task_id: UUID) -> ImageJob:
        if task_id not in jobs:
            raise ToolError("Identifiant de génération d’image inconnu.")
        return jobs[task_id]

    def submit(job: ImageJob, prompt: str) -> None:
        def work() -> None:
            with lock:
                job.report = {"status": "running"}
            started = perf_counter()
            png = None
            try:
                result = recovery.generate_image(prompt, project, None)
                if isinstance(result, DownloadReview):
                    artifact = result.artifact
                    report = {
                        "status": "awaiting_download_approval",
                        "artifact": {"name": artifact.name, "version": artifact.version, "filename": artifact.filename,
                                     "url": artifact.url, "size": artifact.size, "sha256": artifact.sha256,
                                     "license": artifact.license, "license_url": artifact.license_url},
                        "message": "Approuvez le téléchargement dans la CLI interactive avec --prepare et le même cache, "
                                   "puis appelez image_resume.",
                    }
                else:
                    png, proof = result.png, result.proof
                    metadata = proof.get("png", {})
                    if (proof.get("status") != "passed" or not 1 <= len(png) <= MAX_PNG_BYTES
                            or metadata.get("bytes") != len(png) or metadata.get("sha256") != sha256(png).hexdigest()):
                        raise ToolError("Le PNG ne correspond pas au verdict de génération.")
                    report = {"status": "passed", "verdict": proof}
            except (PlanningError, ProjectError) as error:
                report = {"status": "failed", "error": error.error.as_dict()}
            except ToolError as error:
                report = {"status": "failed", "error": {
                    "code": ErrorCode.CONTRACT_POSTCONDITION_FAILED.value, "message": str(error)}}
            except Exception:
                logging.getLogger(__name__).exception("Échec de la génération d’image MCP")
                report = {"status": "failed", "error": {
                    "code": ErrorCode.ENVIRONMENT_OBSERVATION_FAILED.value,
                    "message": "La génération dans le bac local a échoué."}}
            report["wall_s"] = round(perf_counter() - started, 3)
            with lock:
                job.report = report
                if report["status"] != "awaiting_download_approval":
                    job.prompt = None
                if report["status"] == "passed":
                    job.png = png

        scheduler.submit(work)

    @server.tool(annotations=enqueue, structured_output=True)
    def image_start(prompt: str) -> dict[str, str]:
        """Lance une génération CPU headless dans un bac local et retourne son identifiant."""
        try:
            prompt = normalize_prompt(prompt)
        except ProjectError as error:
            raise ToolError(error.error.message) from error
        task_id = uuid4()
        job = ImageJob(prompt)
        with lock:
            jobs[task_id] = job
            submit(job, prompt)
        return {"task_id": str(task_id), "status": "waiting"}

    @server.tool(annotations=enqueue, structured_output=True)
    def image_resume(task_id: UUID) -> dict[str, str]:
        """Revérifie le cache après l’accord humain dans la CLI et reprend la demande initiale."""
        with lock:
            job = find(task_id)
            if job.prompt is None or job.report["status"] != "awaiting_download_approval":
                raise ToolError("Cette génération n’attend pas de téléchargement.")
            job.report = {"status": "waiting"}
            submit(job, job.prompt)
        return {"task_id": str(task_id), "status": "waiting"}

    @server.tool(annotations=read_only, structured_output=True)
    def image_status(task_id: UUID) -> dict[str, Any]:
        """Indique l’état, l’artefact qui exige un accord humain ou le verdict de génération."""
        with lock:
            return {"task_id": str(task_id), **find(task_id).report}

    @server.tool(annotations=read_only, structured_output=True)
    def image_result(task_id: UUID) -> Annotated[CallToolResult, dict[str, Any]]:
        """Retourne le verdict et le PNG vérifié en contenu image MCP pour une tâche réussie."""
        with lock:
            job = find(task_id)
            report = {"task_id": str(task_id), **job.report}
            png = job.png
        content = [TextContent(type="text", text=json.dumps(report, ensure_ascii=False))]
        if png is not None:
            content.append(ImageContent(type="image", mime_type="image/png", data=b64encode(png).decode("ascii")))
        return CallToolResult(content=content, structured_content=report)
