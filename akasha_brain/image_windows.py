"""Exécution de la génération dans Windows Sandbox."""

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
from secrets import token_hex
import shutil
from time import monotonic, sleep
from zipfile import ZipFile

from bench.run_guided_repair import BENCH, file_hash
from contracts.akasha_contracts.errors import ErrorCode

from .image_assets import ENGINE
from .image_execution import MEMORY_MIB
from .notes_desktop import VC_RUNTIME
from .notes_sandbox import CHANNELS, POWERSHELL, guest_exit, read_profile
from .project import fingerprints, validate_in_sandbox
from .project_common import reject

NATIVE_DLLS = (*VC_RUNTIME, "msvcp140_codecvt_ids.dll", "vcomp140.dll")
GUEST = "image_generation_guest.py"
STATUS = "probe_image_generation.ps1"


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
    verifies = staticmethod(verifies_windows)

    def identity(self) -> dict:
        return {"profile": read_profile(),
                "python": {path.relative_to(self.runtime).as_posix(): file_hash(path)
                           for path in self.runtime.rglob("*") if path.is_file()},
                "harness": {name: file_hash(BENCH / "harness" / name) for name in (GUEST, STATUS)},
                "display": file_hash(Path(__file__).with_name("image_preview.py")),
                "backend": file_hash(Path(__file__)),
                "vc": {name: file_hash(Path(os.environ["SystemRoot"]) / "System32" / name) for name in NATIVE_DLLS}}

    def execute(self, stage: Path, prompt: str, checkpoint) -> tuple[dict, bytes]:
        archive = stage / "engine.zip"
        unpack_engine(archive, stage / "engine")
        archive.unlink()
        snapshot = stage / "snapshot"
        snapshot.mkdir()
        frame = "#" + token_hex(3)
        files = {GUEST: (BENCH / "harness" / GUEST).read_bytes(),
                 "image-request.json": json.dumps({"prompt": prompt, "frame": frame}).encode("utf-8")}
        for name, content in files.items():
            (snapshot / name).write_bytes(content)
        shutil.copyfile(BENCH / "harness" / STATUS, stage / STATUS)
        (stage / "validation.json").write_text(json.dumps({"operation": "check", "test": GUEST,
            "test_mode": "script", "files": fingerprints(files), "absent": [], "dependencies": []}), encoding="utf-8")
        report = validate_in_sandbox(stage, self.runtime, checkpoint=checkpoint, sandbox_memory_mib=MEMORY_MIB,
            export_result=lambda sandbox, mount, tag: wait_for_preview(sandbox, mount, tag, frame, checkpoint))
        return report, report.pop("exported")


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


def wait_for_preview(sandbox: str, mount: str, tag: str, frame: str, checkpoint) -> bytes:
    from .image_preview import capture

    deadline = monotonic() + 575
    command = f"{POWERSHELL} -File {mount}\\{STATUS} -Tag {tag}"
    while monotonic() < deadline:
        checkpoint()
        code = guest_exit(sandbox, command)
        if code == 0x4901:
            break
        if code != 0x4900:
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Le moteur n’a pas généré de PNG valide dans le bac.")
        sleep(2)
    else:
        reject(ErrorCode.TIMEOUT_EXCEEDED, "Le moteur a dépassé son délai d’exécution.")
    for _ in range(6):
        checkpoint()
        if (image := capture(frame)) is not None:
            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        sleep(0.5)
    reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Le cadre du résultat est masqué. Gardez Windows Sandbox visible.")
