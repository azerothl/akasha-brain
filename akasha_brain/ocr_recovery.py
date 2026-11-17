"""Relie le moteur OCR local qualifié à une lecture d'image confinée."""

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from time import monotonic

from bench.run_guided_repair import BENCH, execution_limits, file_hash
from contracts.akasha_contracts.errors import ErrorCode

from .model_resources import reserve_model
from .notes_desktop import PROTOCOL_FILE, VC_RUNTIME, stage_ocr
from .notes_sandbox import POWERSHELL, guest_exit, read_profile
from .notes_link_promotion import digest
from .project import fingerprints, project_file, project_input, validate_in_sandbox
from .project_common import digest as digest_bytes, reject

CAPABILITY = "image.ocr"
IMAGE_TYPES = {".png", ".jpg", ".jpeg"}
IMAGE_BYTES = 10 * 1024**2
OUTPUT_BYTES = 97
GUEST = "capability_ocr_guest.py"
EXPORT = "export_capability_ocr.ps1"
MANIFEST = {
    "capability_id": CAPABILITY, "version": "1.0.0", "kind": "adapter",
    "description": "Lire le texte d’une image PNG ou JPEG locale avec RapidOCR.",
    "permissions": {"reads": ["selected-project"], "writes": ["sandbox-scratch"], "execute": ["rapidocr"],
                    "network": []},
    "risk_class": "R1", "sandbox": {"tier": "windows-sandbox", "network_egress": False},
    "side_effects": "local-temporary",
}


@dataclass(frozen=True)
class Candidate:
    runtime: Path
    environment: dict
    fingerprint: str


def tree_hash(folder: Path) -> str:
    return digest({path.relative_to(folder).as_posix(): file_hash(path)
                   for path in folder.rglob("*") if path.is_file()})


def installed_packages_hash(names) -> str:
    # Même périmètre que la copie stage_ocr du banc Notes figé.
    files = {}
    for name in names:
        wheel = distribution(name)
        if wheel.files is None:
            raise RuntimeError(f"Inventaire absent pour le paquet {name}.")
        for member in wheel.files:
            if not member.is_absolute() and ".." not in member.parts and member.suffix != ".pyc":
                files[member.as_posix()] = file_hash(wheel.locate_file(member))
    return digest(files)


def discover(runtime: Path | None) -> Candidate:
    if runtime is None or not (runtime / "python.exe").is_file():
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Le moteur OCR nécessite le Python portable de Windows Sandbox.",
               reason="portable_runtime_missing")
    protocol = json.loads(PROTOCOL_FILE.read_bytes())["ocr"]
    try:
        versions = {name: distribution(name).version for name in protocol["packages"]}
        models = Path(distribution("rapidocr-onnxruntime").locate_file("rapidocr_onnxruntime/models"))
        weights = {name: file_hash(models / name) for name in protocol["model_sha256"]}
        native = Path(os.environ["SystemRoot"]) / "System32"
        dlls = {name: file_hash(native / name) for name in VC_RUNTIME}
        packages = installed_packages_hash(versions)
        python = tree_hash(runtime)
    except (OSError, KeyError, PackageNotFoundError, RuntimeError):
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Il manque des artefacts du moteur RapidOCR local.",
               reason="ocr_artifacts_missing")
    if versions != protocol["packages"] or weights != protocol["model_sha256"]:
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Les artefacts RapidOCR installés diffèrent du moteur qualifié.",
               reason="ocr_artifacts_changed")
    environment = {"ocr": {"packages": versions, "model_sha256": weights}, "native_dependencies": dlls,
                   "python": python, "packages_sha256": packages,
                   "profile": read_profile(),
                   "scripts": {name: file_hash(BENCH / "harness" / name) for name in (GUEST, EXPORT)}}
    return Candidate(runtime, environment, digest({"manifest": MANIFEST, **environment}))


def read_input(project: Path, name: str) -> bytes:
    data = project_input(project_file(project, name), byte_limit=IMAGE_BYTES)
    if not data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L’image doit être un fichier PNG ou JPEG lisible.")
    return data


def read_export(sandbox: str, mount: str, tag: str) -> str:
    command = f"{POWERSHELL} -File {mount}\\{EXPORT} -Tag {tag} -Offset"
    with execution_limits(monotonic() + 110):
        header = guest_exit(sandbox, f"{command} -1")
        size = header & 0xFFFFFF
        if header >> 24 != 0x49 or not 1 <= size <= OUTPUT_BYTES:
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "En-tête d’export OCR invalide.")
        packets = bytearray()
        for offset in range(0, size, 3):
            packet = guest_exit(sandbox, f"{command} {offset}")
            if packet >> 24 != 0x49:
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Paquet d’export OCR invalide.")
            packets.extend((packet & 0xFFFFFF).to_bytes(3, "little"))
    if packets[0] not in (0, 1, 2) or any(packets[size:]):
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Résultat OCR mal formé.")
    if packets[0] == 1:
        if size != 1:
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Erreur OCR mal formée.")
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Image PNG ou JPEG illisible ou trop grande.")
    try:
        text = packets[1:size].decode("utf-8")
    except UnicodeDecodeError:
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Encodage du résultat OCR invalide.")
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Texte OCR mal formé.")
    if packets[0] == 2:
        text += "\n… extrait limité à 96 octets."
    return text or "Aucun texte n’a été reconnu dans l’image."


def run(candidate: Candidate, cancelled, image: bytes | None = None) -> dict:
    def checkpoint():
        if cancelled():
            raise InterruptedError("Demande annulée.")

    def add_native_dlls(portable):
        if tree_hash(portable) != candidate.environment["python"]:
            raise RuntimeError("Le runtime OCR a changé depuis la découverte.")
        for name, expected in candidate.environment["native_dependencies"].items():
            dll = portable / name
            shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / name, dll)
            if file_hash(dll) != expected:
                raise RuntimeError("Une dépendance native OCR a changé.")

    checkpoint()
    with TemporaryDirectory(prefix="akasha-recovery-ocr-") as directory:
        stage = Path(directory)
        snapshot = stage / "snapshot"
        snapshot.mkdir()
        environment = candidate.environment
        sources = {name: (BENCH / "harness" / name).read_bytes() for name in (GUEST, EXPORT)}
        for name, expected in environment["scripts"].items():
            if digest_bytes(sources[name]) != expected:
                raise RuntimeError("Le harnais OCR a changé depuis la découverte.")
        if read_profile() != environment["profile"]:
            raise RuntimeError("Le profil OCR a changé.")
        files = {GUEST: sources[GUEST]}
        if image is not None:
            files["image.input"] = image
        for name, content in files.items():
            (snapshot / name).write_bytes(content)
        (stage / EXPORT).write_bytes(sources[EXPORT])
        (stage / "validation.json").write_text(json.dumps({"operation": "check", "test": GUEST,
            "test_mode": "script", "files": fingerprints(files), "absent": [], "dependencies": []}), encoding="utf-8")
        if (stage_ocr(stage, environment["ocr"]["packages"]) != environment["ocr"]
                or tree_hash(stage / "ocr-packages") != environment["packages_sha256"]):
            raise RuntimeError("Les paquets OCR préparés diffèrent du candidat.")
        checkpoint()
        with reserve_model("onnxruntime", 4096, inside_sandbox=True):
            return validate_in_sandbox(stage, candidate.runtime, checkpoint=checkpoint, prepare_runtime=add_native_dlls,
                                       export_result=read_export if image is not None else None)
