"""Exécution CPU sans fenêtre dans un bac Bubblewrap sans partage hôte inscriptible."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
from selectors import DefaultSelector, EVENT_READ
import shutil
import stat
import subprocess
from time import monotonic
from zipfile import ZipFile

from bench.run_guided_repair import BENCH, file_hash
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import ErrorCode

from .image_assets import LINUX_ENGINE
from .image_execution import MAX_PNG_BYTES, MEMORY_MIB
from .project_common import ProjectError, reject

GUEST = BENCH / "harness" / "image_generation_linux.py"
PYTHON = Path("/usr/bin/python3")
LIBRARIES = ("/usr/lib", "/lib", "/lib64")
NAMESPACES = ("user", "mnt", "net", "pid")
CONTROLS = {"private_namespaces", "network_off", "read_only_input", "private_scratch", "no_privileges", "headless"}


def isolation_verified(controls) -> bool:
    return isinstance(controls, dict) and set(controls) == CONTROLS and all(value is True for value in controls.values())


@dataclass(frozen=True)
class LinuxImageBackend:
    bubblewrap: Path
    tier = "container-rootless"
    label = "Bubblewrap (Linux)"
    artifact = LINUX_ENGINE

    @classmethod
    def local(cls):
        binary = shutil.which("bwrap")
        if os.geteuid() == 0 or not binary or not PYTHON.is_file() or not all(Path(lib).is_dir() for lib in LIBRARIES):
            reject(ErrorCode.CAPABILITY_UNAVAILABLE,
                   "La génération Linux requiert Bubblewrap, Python 3 système et un compte non privilégié.")
        return cls(Path(binary).resolve(strict=True))

    def identity(self) -> dict:
        return {"backend": file_hash(Path(__file__)), "guest": file_hash(GUEST), "bwrap": file_hash(self.bubblewrap),
                "python": file_hash(PYTHON), "kernel": platform.release(), "libc": platform.libc_ver()}

    @staticmethod
    def verifies(proof: dict) -> bool:
        return (proof.get("status") == "passed" and proof.get("sandbox_stopped") is True
                and proof.get("guest_exit_code") == 0 and isolation_verified(proof.get("isolation")))

    def execute(self, stage: Path, prompt: str, checkpoint) -> tuple[dict, bytes]:
        engine = stage / "engine"
        unpack_engine(stage / "engine.zip", engine)
        request = stage / "request"
        request.mkdir()
        shutil.copyfile(GUEST, request / "worker.py")
        (request / "prompt.txt").write_text(prompt, encoding="utf-8")

        command = [str(self.bubblewrap), "--unshare-all", "--unshare-user", "--disable-userns",
                   "--new-session", "--die-with-parent", "--cap-drop", "ALL", "--clearenv",
                   "--setenv", "LD_LIBRARY_PATH", "/engine", "--setenv", "LC_ALL", "C.UTF-8",
                   "--ro-bind", str(PYTHON), str(PYTHON)]
        for directory in LIBRARIES:
            command.extend(("--ro-bind", directory, directory))
        command.extend(("--ro-bind", str(engine), "/engine", "--ro-bind", str(stage / "image-model.gguf"), "/weights.gguf",
                        "--ro-bind", str(request), "/request", "--proc", "/proc", "--dev", "/dev",
                        "--size", str(32 * 1024**2), "--tmpfs", "/work", "--chdir", "/work", "--remount-ro", "/",
                        str(PYTHON), "-I", "-B", "-X", "utf8", "/request/worker.py",
                        str(MEMORY_MIB * 1024**2), str(MAX_PNG_BYTES)))
        command.extend(os.readlink(f"/proc/self/ns/{kind}") for kind in NAMESPACES)
        checkpoint()
        deadline = monotonic() + 570
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as process:
            try:
                line = read_stream(process.stdout, 1024, min(deadline, monotonic() + 15), checkpoint, line=True)
                controls = json.loads(line) if line else None
                denied = authorize({"risk_class": "R1", "confinement_verified": isolation_verified(controls)})
                if denied:
                    raise ProjectError(denied)
                process.stdin.write(b"+")
                process.stdin.close()
                png = read_stream(process.stdout, MAX_PNG_BYTES, deadline, checkpoint)
                code = process.wait(timeout=max(0.1, deadline - monotonic()))
                if code != 0 or not png:
                    reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Le moteur Linux n’a pas exporté de PNG.", guest_exit_code=code)
            finally:
                if process.poll() is None:
                    process.kill()
        return {"status": "passed", "sandbox_stopped": True, "guest_exit_code": code,
                "read_only_input": True, "isolation": controls}, png


def read_stream(pipe, limit: int, deadline: float, checkpoint, *, line: bool = False) -> bytes:
    result = bytearray()
    with DefaultSelector() as readable:
        readable.register(pipe, EVENT_READ)
        while True:
            checkpoint()
            remaining = deadline - monotonic()
            if remaining <= 0:
                reject(ErrorCode.TIMEOUT_EXCEEDED, "Délai dépassé dans le bac d’images Linux.")
            if not readable.select(min(remaining, 0.25)):
                continue
            chunk = os.read(pipe.fileno(), min(65536, limit + 1 - len(result)))
            if not chunk:
                return bytes(result)
            result.extend(chunk)
            if len(result) > limit:
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Flux exporté au-delà de la taille autorisée.")
            if line and result.endswith(b"\n"):
                return bytes(result)


def unpack_engine(archive: Path, destination: Path) -> None:
    destination.mkdir()
    copied = set()
    with ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = Path(member.filename).name
            if name != "sd-cli" and not re.fullmatch(r"[A-Za-z0-9_.+-]{1,110}\.so(?:\.\d+)*", name):
                continue
            kind = stat.S_IFMT(member.external_attr >> 16)
            if kind not in (0, stat.S_IFREG) or name in copied or member.file_size > 64 * 1024**2 or len(copied) >= 40:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Contenu inattendu dans l’archive Linux du moteur.")
            output = destination / name
            with bundle.open(member) as source, output.open("xb") as stream:
                shutil.copyfileobj(source, stream)
            output.chmod(0o700)
            copied.add(name)
    if "sd-cli" not in copied:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L’archive Linux ne contient pas sd-cli.")
