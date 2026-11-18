"""Exécution sans fenêtre dans Windows Sandbox avec un export HCS borné."""

from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
from secrets import token_hex
import shutil
import subprocess
from time import monotonic, sleep
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

from bench.run_guided_repair import BENCH, file_hash, wsb
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import ErrorCode

from .image_assets import ENGINE
from .image_execution import MAX_PNG_BYTES, MEMORY_MIB
from .notes_desktop import VC_RUNTIME
from .notes_sandbox import CHANNELS, POWERSHELL, active_sandboxes, read_profile
from .project_common import ProjectError, reject

NATIVE_DLLS = (*VC_RUNTIME, "msvcp140_codecvt_ids.dll", "vcomp140.dll")
GUEST = "image_generation_guest.py"
PROBES = ("probe_notes_isolation.ps1", "probe_guest_channels.ps1")
MAX_ENVELOPE_BYTES = 4 * ((MAX_PNG_BYTES + 2) // 3) + 256


def verifies_windows(proof: dict) -> bool:
    return (proof.get("status") == "passed" and proof.get("sandbox_stopped") is True
            and proof.get("read_only_input") is True and proof.get("guest_exit_code") == 0x4700
            and proof.get("channel_probe") in (0x410F, 0x411F)
            and list(CHANNELS) == proof.get("disabled_channels"))


@dataclass(frozen=True)
class WindowsImageBackend:
    runtime: Path
    tier = "windows-sandbox"
    label = "Windows Sandbox"
    artifact = ENGINE

    @staticmethod
    def verifies(proof: dict) -> bool:
        return (proof.get("status") == "passed" and proof.get("sandbox_stopped") is True
                and proof.get("read_only_input") is True and proof.get("guest_exit_code") == 0
                and proof.get("mount_probe") == 0x450F and proof.get("channel_probe") == 0x411F
                and proof.get("headless") is True and proof.get("export_transport") == "hcs-stdout"
                and list(CHANNELS) == proof.get("disabled_channels"))

    def identity(self) -> dict:
        return {"profile": read_profile(),
                "python": {path.relative_to(self.runtime).as_posix(): file_hash(path)
                           for path in self.runtime.rglob("*") if path.is_file()},
                "harness": {name: file_hash(BENCH / "harness" / name) for name in (GUEST, *PROBES)},
                "hcsdiag": file_hash(system32() / "hcsdiag.exe"),
                "backend": file_hash(Path(__file__)),
                "vc": {name: file_hash(Path(os.environ["SystemRoot"]) / "System32" / name) for name in NATIVE_DLLS}}

    def execute(self, stage: Path, prompt: str, checkpoint) -> tuple[dict, bytes]:
        archive = stage / "engine.zip"
        unpack_engine(archive, stage / "engine")
        archive.unlink()
        shutil.copytree(self.runtime, stage / "python")
        for script in (GUEST, *PROBES):
            shutil.copyfile(BENCH / "harness" / script, stage / script)
        (stage / "image-prompt.txt").write_text(prompt, encoding="utf-8")
        return execute_headless(stage, checkpoint)


def unpack_engine(archive: Path, destination: Path):
    destination.mkdir()
    copied = set()
    with ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = PurePosixPath(member.filename).name
            if name.casefold() != "sd-cli.exe" and not name.casefold().endswith(".dll"):
                continue
            if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name) or name.casefold() in copied
                    or member.file_size > 64 * 1024**2 or len(copied) >= 32):
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Contenu binaire inattendu dans l’archive du moteur.")
            with bundle.open(member) as source, (destination / name).open("xb") as output:
                shutil.copyfileobj(source, output)
            copied.add(name.casefold())
    if "sd-cli.exe" not in copied:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L’archive du moteur ne contient pas sd-cli.exe.")
    for name in NATIVE_DLLS:
        if name not in copied:
            shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / name, destination / name)


def system32() -> Path:
    return Path(os.environ["SystemRoot"]) / "System32"


def tool_stdout(tool: str, arguments, limit: int, timeout: float, checkpoint) -> bytes:
    deadline = monotonic() + timeout
    command = [str(system32() / tool), *arguments]
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW) as process, ThreadPoolExecutor(1) as workers:
        reading = workers.submit(process.stdout.read, limit + 1)
        try:
            while True:
                checkpoint()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    reject(ErrorCode.TIMEOUT_EXCEEDED, "Délai dépassé dans le bac d’images Windows.")
                try:
                    data = reading.result(timeout=min(remaining, 0.25))
                    break
                except FutureTimeout:
                    continue
            if len(data) > limit:
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Flux Windows au-delà de la taille autorisée.")
            if process.wait(timeout=max(0.1, deadline - monotonic())) != 0:
                reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "L’outil de calcul Windows a échoué.",
                       tool=tool, exit_code=process.returncode)
            return data
        finally:
            if process.poll() is None:
                process.kill()


def compute_ids(checkpoint) -> set[str]:
    rows = json.loads(tool_stdout("hcsdiag.exe", ("list", "-raw"), 65_536, 15, checkpoint))
    return {str(UUID(row["Id"])) for row in rows
            if row["Owner"] == "WindowsSandbox" and row["SystemType"] == "VirtualMachine" and row["State"] == "Running"}


def assert_headless(checkpoint):
    arguments = ("/FO", "CSV", "/NH", "/FI", "IMAGENAME eq WindowsSandboxRemoteSession.exe")
    listing = tool_stdout("tasklist.exe", arguments, 8192, 8, checkpoint)
    if b"windowssandboxremotesession.exe" in listing.lower():
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Un client graphique Windows Sandbox est ouvert.")


def system_guest_exit(sandbox: str, command: str) -> int:
    return wsb("exec", "--id", sandbox, "--run-as", "System", "--command", command)["ExitCode"]


def decode_export(packet: bytes) -> bytes:
    try:
        record = json.loads(packet)
        if (not isinstance(record, dict) or set(record) != {"bytes", "sha256", "data"}
                or type(record["bytes"]) is not int or not 1 <= record["bytes"] <= MAX_PNG_BYTES
                or not isinstance(record["data"], str)):
            raise ValueError("Enveloppe PNG invalide")
        data = b64decode(record["data"], validate=True)
        if len(data) != record["bytes"] or sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Empreinte de sortie invalide")
    except (ValueError, TypeError):
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Le PNG reçu de Windows ne correspond pas à son enveloppe.")
    return data


def execute_headless(stage: Path, checkpoint) -> tuple[dict, bytes]:
    def export(compute, mount):
        command = ("exec", compute, fr"{mount}\python\python.exe", "-I", "-B", "-X", "utf8",
                   fr"{mount}\{GUEST}", str(MAX_PNG_BYTES))
        return decode_export(tool_stdout("hcsdiag.exe", command, MAX_ENVELOPE_BYTES, 570, checkpoint))

    return run_headless_guest(stage, checkpoint, MEMORY_MIB, export)


def run_headless_guest(stage, checkpoint, memory_mib, export):
    # Image and CPU ASR callers already hold the inference lease.
    from .whisper_resident import release
    release()
    sandbox = str(uuid4())
    compute, mount, mount_code, channels = start_headless_guest(stage, checkpoint, memory_mib, sandbox)
    try:
        data = export(compute, mount)
        assert_headless(checkpoint)
    finally:
        stop_headless_guest(sandbox)
    return {"status": "passed", "sandbox_stopped": True, "sandbox_id": sandbox, "guest_exit_code": 0,
            "read_only_input": True, "mount_probe": mount_code, "channel_probe": channels,
            "disabled_channels": list(CHANNELS), "headless": True, "export_transport": "hcs-stdout"}, data


def stop_headless_guest(sandbox):
    if sandbox in active_sandboxes():
        wsb("stop", "--id", sandbox)
    if sandbox in active_sandboxes():
        raise RuntimeError("Arrêt du bac non confirmé.")


class GuestStartError(RuntimeError):
    pass


def start_headless_guest(stage, checkpoint, memory_mib, sandbox, *, vgpu=False):
    if active_sandboxes():
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Une session Windows Sandbox est déjà active.")
    assert_headless(checkpoint)
    before = compute_ids(checkpoint)
    tag = token_hex(4)
    mount = fr"C:\AkashaGuidedInput-{tag}"
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    profile = ElementTree.fromstring(read_profile())
    profile.find("MemoryInMB").text = str(memory_mib)
    if vgpu:
        profile.find("VGpu").text = "Enable"
    try:
        try:
            started = wsb("start", "--id", sandbox, "--config", ElementTree.tostring(profile, encoding="unicode"))
        except RuntimeError as error:
            raise GuestStartError("Échec du démarrage de Windows Sandbox.") from error
        if started["Id"].lower() != sandbox:
            raise RuntimeError("Identifiant du bac inattendu.")
        for _ in range(12):
            checkpoint()
            try:
                if system_guest_exit(sandbox, r"C:\Windows\System32\cmd.exe /c exit 0") == 0:
                    break
            except RuntimeError:
                pass
            sleep(1)
        else:
            reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Le bac Windows sans fenêtre n’est pas prêt.")

        new = compute_ids(checkpoint) - before
        if active_sandboxes() != [sandbox] or len(new) != 1:
            reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Impossible d’associer le bac au système de calcul Windows.")
        compute = next(iter(new))
        wsb("share", "--id", sandbox, "--host-path", str(stage), "--sandbox-path", mount)
        mount_code = system_guest_exit(sandbox, f"{POWERSHELL} -File {mount}\\{PROBES[0]} -Tag {tag}")
        channels = system_guest_exit(sandbox, f"{POWERSHELL} -File {mount}\\{PROBES[1]}")
        denied = authorize({"risk_class": "R1", "confinement_verified": mount_code == 0x450F and channels == 0x411F})
        if denied:
            raise ProjectError(denied)
        assert_headless(checkpoint)
        witness = ("exec", compute, r"C:\Windows\System32\cmd.exe", "/c", "type", fr"{mount}\isolation-sentinel.txt")
        if tool_stdout("hcsdiag.exe", witness, 128, 15, checkpoint) != tag.encode("ascii"):
            reject(ErrorCode.PERMISSION_DENIED, "Le flux HCS n’appartient pas au bac préparé.")
        return compute, mount, mount_code, channels
    except BaseException:
        stop_headless_guest(sandbox)
        raise
