"""Issues de planification et rejeu d’une recomposition locale R0."""

from dataclasses import dataclass
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .planning import PlanningError

COMPARE = re.compile(r"(?:compare|comparez)\s+(?:(?:les\s+)?(?:documents|fichiers)\s+)?"
                     r"@\s+et\s+@[\s?!.]*", re.IGNORECASE)
COMPARE_TOOL = "documents.compare"
TRANSCRIBE = re.compile(r"(?:transcris|transcrivez|transcrire)\s+(?:le\s+fichier\s+)?@[\s?!.]*", re.I)
TRANSCRIPTION = "audio.transcribe"
AUDIO_FORMATS = {".wav", ".flac"}
TERMINAL = {
    ErrorCode.CAPABILITY_UNAVAILABLE: "missing",
    ErrorCode.NEEDS_CLARIFICATION: "needs_clarification",
    ErrorCode.PERMISSION_DENIED: "denied",
    ErrorCode.APPROVAL_REQUIRED: "awaiting_approval",
}
LABELS = {
    "missing": "Capacité manquante",
    "abstain": "Abstention",
    "denied": "Accès refusé",
    "awaiting_approval": "Accord requis",
}


@dataclass(frozen=True)
class GapReview:
    request_id: str


def diagnose(error: AkashaError) -> AkashaError:
    outcome = error.details.get("outcome") or TERMINAL.get(error.code, "failed")
    return AkashaError(error.code, error.message, {**error.details, "outcome": outcome})


def mask_references(request: str, refs: list[str]) -> str:
    masked = request.strip()
    for name in sorted(refs, key=len, reverse=True):
        escaped = re.escape(name)
        pattern = rf'(?:"{escaped}"|`{escaped}`|«\s*{escaped}\s*»|{escaped})'
        masked = re.sub(pattern, "@", masked, count=1)
    return masked


def compare_intent(request: str, refs: list[str], catalog: dict) -> dict | None:
    """Reconstruit une comparaison explicite quand le modèle n’a trouvé aucun outil."""
    manifest = catalog.get(COMPARE_TOOL)
    if (len(refs) == 2 and manifest and manifest.get("risk_class") == "R0"
            and COMPARE.fullmatch(mask_references(request, refs))):
        return {"tool": COMPARE_TOOL, "refs": [1, 2], "detail": ""}
    return None


def transcription_context(request: str, refs: list[str]) -> str | None:
    if len(refs) == 1 and TRANSCRIBE.fullmatch(mask_references(request, refs)):
        extension = Path(refs[0]).suffix.lower()
        if extension in AUDIO_FORMATS:
            return extension
    return None


def transcription_proposal(contexts: tuple[str, ...]) -> dict:
    return {
        "outcome": "construction_proposed", "level": "E", "capability": TRANSCRIPTION, "contexts": contexts,
        "tried": ["local_registry", "declared_recovery", "read_only_recomposition"],
        "expected": "Audio local vers transcription UTF-8 horodatée",
        "evaluation": ["WAV et FLAC synthétiques", "transcription de référence et taux d’erreur",
                       "budget CPU et absence d’écriture hors bac"],
        "required_evidence": ["source, version, empreinte et licence du spécialiste", "accord par téléchargement"],
        "risk": "R3 pour l’acquisition des artefacts", "rollback": "maintien du registre actif",
    }


def replay_comparison(compare) -> dict:
    """Mesure deux témoins synthétiques avant d’autoriser le chemin reconstruit."""
    with TemporaryDirectory(prefix="akasha-gap-replay-") as directory:
        root = Path(directory)
        before, after = root / "avant.md", root / "apres.md"
        original = "Titre\nancien\n"
        before.write_text(original, encoding="utf-8")
        after.write_text(original, encoding="utf-8")
        inputs = (before.name, after.name)
        identity = compare(root, inputs) == "Les deux documents ont le même contenu."
        after.write_text("Titre\nnouveau\n", encoding="utf-8")
        report = compare(root, inputs)
        expected_diff = report.endswith(" Titre\n-ancien\n+nouveau\n")
        untouched = before.read_text(encoding="utf-8") == original
    if not all((identity, expected_diff, untouched)):
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_POSTCONDITION_FAILED,
            "Le chemin de comparaison candidat a échoué au rejeu synthétique.",
            {"outcome": "abstain", "capability": COMPARE_TOOL}))
    return {"level": "A", "candidate": COMPARE_TOOL, "synthetic_checks": 3, "passed": True}
