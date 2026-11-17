"""Contrat d’exécution et validation commune des images exportées."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol

from contracts.akasha_contracts.errors import ErrorCode

from .image_assets import Artifact
from .project_common import reject

MEMORY_MIB = 8192
MAX_PNG_BYTES = 2 * 1024**2
DIMENSIONS = (512, 512)


class ImageBackend(Protocol):
    tier: str
    label: str
    artifact: Artifact

    def identity(self) -> dict: ...

    def execute(self, stage: Path, prompt: str, checkpoint: Callable[[], None]) -> tuple[dict, bytes]: ...

    def verifies(self, proof: dict) -> bool: ...


@dataclass(frozen=True)
class ImageResult:
    png: bytes
    proof: dict


def validate_export(raw: bytes) -> tuple[bytes, dict]:
    from PIL import Image

    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_PNG_BYTES:
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Taille de la sortie PNG invalide.")
    try:
        with Image.open(BytesIO(raw), formats=("PNG",)) as image:
            if image.size != DIMENSIONS or getattr(image, "is_animated", False):
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Dimensions ou animation PNG inattendues.")
            image.verify()
        with Image.open(BytesIO(raw), formats=("PNG",)) as image:
            pixels = image.convert("RGB")
            if len(pixels.resize((24, 24)).getcolors(576) or ()) < 24:
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "L’image exportée est vide ou uniforme.")
            pixels.info.clear()
            with BytesIO() as stream:
                pixels.save(stream, format="PNG")
                png = stream.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Le flux exporté n’est pas un PNG valide.")
    if not 1 <= len(png) <= MAX_PNG_BYTES:
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Le PNG normalisé dépasse sa taille autorisée.")
    return png, {"format": "PNG", "width": DIMENSIONS[0], "height": DIMENSIONS[1], "bytes": len(png),
                 "sha256": sha256(png).hexdigest(), "input_sha256": sha256(raw).hexdigest()}
