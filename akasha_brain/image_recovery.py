"""Découverte, préparation et qualification communes du générateur d’images."""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
import platform
import shutil
from tempfile import TemporaryDirectory

from bench.run_guided_repair import file_hash
from contracts.akasha_contracts.errors import ErrorCode
from contracts.akasha_contracts.validate import validate

from . import image_assets
from .image_execution import ImageBackend, ImageResult as ImageResult, MEMORY_MIB, validate_export
from .model_resources import reserve_model
from .notes_link_promotion import digest
from .project_common import reject

CAPABILITY = "image.generate"
QUALIFICATION = "A photo of a small red sailboat on a clear blue lake, daylight"
MANIFEST = {
    "capability_id": CAPABILITY, "version": "1.0.0", "kind": "adapter",
    "description": "Générer une image à partir de texte sur CPU avec SD-Turbo.",
    "permissions": {"reads": [], "writes": ["sandbox-scratch"], "execute": ["sd-cli"], "network": []},
    "risk_class": "R1", "sandbox": {"tier": "windows-sandbox", "network_egress": False},
    "side_effects": "local-temporary",
}


def normalize_prompt(prompt: str) -> str:
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 1500 or any(ord(char) < 32 and char not in "\t\n" for char in prompt):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Décrivez l’image souhaitée en 1 500 caractères au maximum.")
    return prompt


@dataclass(frozen=True)
class Candidate:
    backend: ImageBackend
    archive: Path
    model: Path
    fingerprint: str


def select_backend(runtime: Path | None) -> ImageBackend:
    system = platform.system()
    if platform.machine().lower() not in {"amd64", "x86_64"} or system not in {"Windows", "Linux"}:
        reject(ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED, "Le candidat SD-Turbo requiert Windows ou Linux x86_64.")
    if system == "Linux":
        from .image_linux import LinuxImageBackend

        return LinuxImageBackend.local()
    if runtime is None or not all((runtime / name).is_file() for name in ("python.exe", "python312.dll")):
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Configurez le Python portable de Windows Sandbox avant la génération.")
    from .image_windows import WindowsImageBackend, system32

    if not (system32() / "hcsdiag.exe").is_file():
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "La sortie headless requiert l’outil système hcsdiag.exe.")
    return WindowsImageBackend(runtime)


def discover(cache: Path, runtime: Path | None) -> Candidate | image_assets.DownloadReview:
    if find_spec("PIL") is None:
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Pillow est requis pour valider le PNG exporté.")
    backend = select_backend(runtime)
    installed = []
    for artifact in (backend.artifact, image_assets.MODEL):
        path = image_assets.find_local(cache, artifact)
        if path is None:
            return image_assets.review_download(cache, artifact)
        installed.append(path)
    manifest = {**MANIFEST, "sandbox": {**MANIFEST["sandbox"], "tier": backend.tier}}
    if errors := validate(manifest, "CapabilityManifest"):
        reject(errors[0].code, errors[0].message)
    signature = digest({"manifest": manifest, "memory": MEMORY_MIB, "environment": backend.identity(),
                        "engine": backend.artifact.sha256, "model": image_assets.MODEL.sha256,
                        "export": file_hash(Path(__file__).with_name("image_execution.py"))})
    return Candidate(backend, *installed, signature)


def verifies(candidate: Candidate, proof: dict) -> bool:
    return (proof.get("backend") == candidate.backend.tier and proof.get("candidate_sha256") == candidate.fingerprint
            and isinstance(proof.get("png"), dict) and candidate.backend.verifies(proof))


def run(candidate: Candidate, prompt: str, checkpoint) -> ImageResult:
    checkpoint()
    with TemporaryDirectory(prefix="akasha-cpu-image-") as directory:
        stage = Path(directory)
        for source, filename, artifact in ((candidate.archive, "engine.zip", candidate.backend.artifact),
                                           (candidate.model, "image-model.gguf", image_assets.MODEL)):
            path = stage / filename
            shutil.copyfile(source, path)
            if not image_assets.matches(path, artifact):
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Un artefact local a changé pendant la préparation.")
        checkpoint()
        with reserve_model("sd-turbo", MEMORY_MIB, inside_sandbox=True):
            proof, raw = candidate.backend.execute(stage, prompt, checkpoint)
        if not candidate.backend.verifies(proof):
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "La preuve d’exécution isolée est incomplète.")
        png, receipt = validate_export(raw)
        proof = {**proof, "backend": candidate.backend.tier, "candidate_sha256": candidate.fingerprint, "png": receipt}
        return ImageResult(png, proof)
