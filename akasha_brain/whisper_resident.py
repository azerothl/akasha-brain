"""Resident whisper.cpp CUDA server inside a verified offline Windows Sandbox.

The session ticket is private to the host. All uses and lifecycle changes are
serialized by the existing cross-process inference lease.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import sleep, time
from uuid import UUID, uuid4

from bench.run_guided_repair import BENCH, file_hash
from contracts.akasha_contracts.errors import ErrorCode
from .desktop_settings import app_directory
from .image_windows import GuestStartError, PROBES, assert_headless, start_headless_guest, stop_headless_guest, system32, tool_stdout
from .model_resources import inference_lease
from .notes_desktop import VC_RUNTIME
from .notes_sandbox import active_sandboxes
from .planning import PlanningError
from .project_common import ProjectError, project_scope, reject

IDLE_SECONDS = 120
VRAM_MIB = 1200
BINARIES = {
    "whisper-server.exe": "3fad850119836df059ac15a5339cf6e061bdd7072bf223906c531a1d8069ac68",
    "whisper.dll": "532a900e74ebcc2fbc3a8bc986bd1052e7c5310e19338e6fa91d2f4c5023241e",
    "ggml.dll": "9679b00183036f667fdc097f7b5834852a11c654cef545c70f238285b1eca2e1",
    "ggml-base.dll": "fb3a4f12f90a3b44503914f2f8f1b0d89658a7b165dfbc424e157200ec4c6dd8",
    "ggml-cpu.dll": "087e9eb9d29245efd61a69190f0f56992a6b75337d837238b09ec4d84a77c29d",
    "ggml-cuda.dll": "214eecd0080f1db0d73ad0e750aa81de5c4eb22b191372bef6f3934decda5587",
    "cudart64_12.dll": "d28e42265da7462162a54da6b7a99ea4fa2caf8139d862bb500db875d0b32dfc",
    "cublas64_12.dll": "e40202fe4223c1cd2d2dce7beec59e1ed61c7801bd827309183be9b50e358f4c",
    "cublasLt64_12.dll": "2a896460bef60ed57ef32b0875812f355a6984e671d638bb632f5e8c1d7a831f",
    "SDL2.dll": "de23db1694a3c7a4a735e7ecd3d214b2023cc2267922c6c35d30c7fc7370d677",
}


class GpuUnavailable(RuntimeError):
    pass


def cache_path():
    value = os.environ.get("AKASHA_WHISPER_GPU_CACHE")
    if value is None:
        try:
            value = (app_directory()/"whisper-gpu-cache.txt").read_text("utf-8-sig").strip()
        except (OSError, UnicodeError):
            return None
    return Path(value).resolve() if value and Path(value).is_absolute() else None


def ticket_file():
    return app_directory()/"whisper-resident.json"


def read_ticket():
    try:
        return json.loads(ticket_file().read_bytes())
    except FileNotFoundError:
        return None


def publish(ticket):
    path = ticket_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(ticket), "utf-8")
    temp.replace(path)


def stage_path(ticket):
    root = Path(ticket["cache"])
    if not root.is_absolute():
        raise ValueError("Cache de résidence invalide")
    folder = root/(".akasha-resident-"+str(UUID(ticket["sandbox"])))
    if folder.resolve() != folder:
        raise ValueError("Dossier de résidence redirigé")
    return folder


def release(ticket=None):
    """Called with the host inference lease held."""
    ticket = ticket or read_ticket()
    if not ticket:
        return
    stage = stage_path(ticket)
    stop_headless_guest(str(UUID(ticket["sandbox"])))
    if stage.exists():
        shutil.rmtree(stage)
    ticket_file().unlink(missing_ok=True)


def expire(session):
    # One private, short-lived watcher per guest, independent of desktop/MCP exit.
    while True:
        current = read_ticket()
        if not current or current["sandbox"] != session:
            return
        remaining = current["used"] + IDLE_SECONDS - time()
        if remaining > 0:
            sleep(min(remaining, 10))
            continue
        try:
            with inference_lease():
                current = read_ticket()
                if current and current["sandbox"] == session and time()-current["used"] >= IDLE_SECONDS:
                    release(current)
                    return
        except PlanningError:
            sleep(1)


def yield_to_sandbox():
    if os.name == "nt" and ticket_file().is_file():
        with inference_lease():
            release()


def guest(ticket, action, checkpoint, *arguments):
    mount = ticket["mount"]
    if not re.fullmatch(r"C:\\AkashaGuidedInput-[a-f0-9]{8}", mount):
        raise ValueError("Montage GPU invalide")
    cmd = ("exec", str(UUID(ticket["compute"])), r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
           "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
           mount+r"\whisper_resident.ps1", action, *arguments)
    try:
        return tool_stdout("hcsdiag.exe", cmd, 2*1024**2, 180, checkpoint)
    except ProjectError as error:
        if error.error.code in (ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, ErrorCode.TIMEOUT_EXCEEDED):
            raise GpuUnavailable("cuda_start" if action == "start" else "cuda_inference") from error
        raise


def start(cache, model, model_hash, scope, checkpoint):
    binaries = {cache/"whisper"/"Release"/name: expected for name, expected in BINARIES.items()}
    if not all(path.is_file() for path in binaries):
        raise GpuUnavailable("cuda_runtime_missing")
    ticket = dict(sandbox=str(uuid4()), cache=str(cache), model=str(model), project=scope, used=time())
    stage = stage_path(ticket)
    stage.mkdir()
    try:
        publish(ticket)
        subprocess.Popen([sys.executable, "-m", "akasha_brain.whisper_resident", ticket["sandbox"]],
                         cwd=Path(__file__).resolve().parent.parent, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        for source, expected in {model: model_hash, **binaries}.items():
            checkpoint()
            target = stage/source.name
            shutil.copyfile(source, target)
            if file_hash(target) != expected:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Empreinte Whisper GPU inattendue.", artifact=source.name)
        for name in (*VC_RUNTIME, "vcomp140.dll"):
            shutil.copyfile(system32()/name, stage/name)
        for name in (*PROBES, "whisper_resident.ps1"):
            shutil.copyfile(BENCH/"harness"/name, stage/name)
        try:
            compute, mount, _, _ = start_headless_guest(stage, checkpoint, 4096, ticket["sandbox"], vgpu=True)
        except GuestStartError as error:
            raise GpuUnavailable("vgpu_unavailable") from error
        ticket.update(compute=compute, mount=mount)
        witness = guest(ticket, "start", checkpoint)
        if not re.fullmatch(rb"CUDA0 [1-9][0-9]*", witness):
            raise GpuUnavailable("cuda_unconfirmed")
        ticket["pid"] = int(witness.split()[1])
        return ticket
    except BaseException:
        if ticket_file().exists():
            release(ticket)
        elif stage.exists():
            shutil.rmtree(stage)
        raise


def transcribe(cache, model, model_hash, project, raw, suffix, checkpoint):
    """Both entry points use the same resident for the currently selected project."""
    if cache.is_relative_to(project.resolve()) or ticket_file().resolve().is_relative_to(project.resolve()):
        reject(ErrorCode.PERMISSION_DENIED, "Le cache GPU doit être hors du projet.")
    scope = project_scope(project)
    ticket = read_ticket()
    if ticket and (ticket["cache"] != str(cache) or ticket["model"] != str(model) or ticket["project"] != scope
                   or not ticket.get("pid") or time()-ticket["used"] >= IDLE_SECONDS
                   or ticket["sandbox"] not in active_sandboxes()):
        release(ticket)
        ticket = None
    warm = bool(ticket)
    if not ticket:
        ticket = start(cache, model, model_hash, scope, checkpoint)
    audio = stage_path(ticket)/("audio-"+uuid4().hex+suffix)
    try:
        assert_headless(checkpoint)
        audio.write_bytes(raw)
        packet = guest(ticket, "transcribe", checkpoint, audio.name)
        assert_headless(checkpoint)
        checkpoint()
        ticket.update(used=time())
        publish(ticket)
        return packet, {"device": "cuda", "reused": warm, "residency_id": ticket["sandbox"]}
    except BaseException:
        release(ticket)
        raise
    finally:
        audio.unlink(missing_ok=True)


if __name__ == "__main__":
    expire(str(UUID(sys.argv[1])))
