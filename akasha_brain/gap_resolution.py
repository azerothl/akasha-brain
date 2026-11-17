"""Issues de planification et rejeu d’une recomposition locale R0."""

from codecs import BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE
from dataclasses import dataclass
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .planning import PlanningError

COMPARE = re.compile(r"(?:compare|comparez)\s+(?:(?:les\s+)?(?:documents|fichiers)\s+)?"
                     r"@\s+et\s+@[\s?!.]*", re.IGNORECASE)
COMPARE_TOOL = "documents.compare"
READ_COMPARE_SKILL = "documents.read_then_compare"
READ = re.compile(r"lis\s+(?:le\s+fichier\s+)?@[\s?!.]*", re.IGNORECASE)
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


def read_compare_steps(parts: list[str], part_refs: list[list[str]], refs: list[str], catalog: dict) -> list[dict] | None:
    if len(parts) != 2:
        return None
    read_refs, comparison_refs = part_refs
    manifest = catalog.get("file.read")
    if (len(read_refs) != 1 or not manifest or manifest.get("risk_class") != "R0"
            or not READ.fullmatch(mask_references(parts[0], read_refs))
            or not all(name in refs for name in read_refs + comparison_refs)):
        return None
    if not compare_intent(parts[1], comparison_refs, catalog):
        return None
    return [
        {"tool": "file.read", "refs": [refs.index(read_refs[0]) + 1], "detail": ""},
        {"tool": COMPARE_TOOL, "refs": [refs.index(name) + 1 for name in comparison_refs], "detail": ""},
    ]


def transcription_context(request: str, refs: list[str]) -> str | None:
    if len(refs) == 1 and TRANSCRIBE.fullmatch(mask_references(request, refs)):
        extension = Path(refs[0]).suffix.lower()
        if extension in AUDIO_FORMATS:
            return extension
    return None


def transcription_proposal(contexts: tuple[str, ...]) -> dict:
    return {
        "outcome": "construction_proposed", "level": "E", "capability": TRANSCRIPTION, "contexts": contexts,
        "admissibility": {
            "A": "Aucun outil déclaré ne produit une transcription audio.",
            "B": "La conversion d’encodage des documents produit du texte à partir de texte.",
            "C": "La compétence de lecture et de comparaison exige des documents texte.",
            "D": "Le fournisseur RapidOCR traite des images.",
        },
        "expected": "Audio local vers transcription UTF-8 horodatée",
        "evaluation": ["WAV et FLAC synthétiques", "transcription de référence et taux d’erreur",
                       "budget CPU et absence d’écriture hors bac"],
        "required_evidence": ["source, version, empreinte et licence du spécialiste", "accord par téléchargement"],
        "required_rights": ["licence des artefacts", "autorisation par téléchargement"],
        "cost": {"status": "to_measure", "metrics": ["RAM maximale", "chargement à froid", "temps CPU"]},
        "risk": "R3 pour l’acquisition des artefacts", "rollback": "maintien du registre actif",
    }


def decode_with_utf16_bom(data: bytes) -> str:
    if data.startswith((BOM_UTF32_LE, BOM_UTF32_BE)):
        raise UnicodeDecodeError("utf-16", data, 0, 4, "marque d’encodage UTF-32")
    if not data.startswith((BOM_UTF16_LE, BOM_UTF16_BE)):
        return data.decode("utf-8-sig")
    text = data.decode("utf-16")
    if "\0" in text:
        raise UnicodeDecodeError("utf-16", data, 0, len(data), "octet nul dans le texte décodé")
    return text


def replay_comparison(compare, *, utf16: bool = False) -> dict:
    """Mesure deux témoins synthétiques avant d’autoriser le chemin reconstruit."""
    level = "B" if utf16 else "A"
    with TemporaryDirectory(prefix="akasha-gap-replay-") as directory:
        root = Path(directory)
        before, after = root / "avant.md", root / "apres.md"
        original = "Titre\nancien\n"
        original_bytes = BOM_UTF16_LE + original.encode("utf-16-le") if utf16 else original.encode("utf-8")
        before.write_bytes(original_bytes)
        after.write_text(original, encoding="utf-8")
        inputs = (before.name, after.name)
        identity = compare(root, inputs) == "Les deux documents ont le même contenu."
        modified = "Titre\nnouveau\n"
        modified_bytes = BOM_UTF16_BE + modified.encode("utf-16-be") if utf16 else modified.encode("utf-8")
        after.write_bytes(modified_bytes)
        report = compare(root, inputs)
        expected_diff = report.endswith(" Titre\n-ancien\n+nouveau\n")
        untouched = before.read_bytes() == original_bytes and after.read_bytes() == modified_bytes
    if not all((identity, expected_diff, untouched)):
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_POSTCONDITION_FAILED,
            "Le chemin de comparaison candidat a échoué au rejeu synthétique.",
            {"outcome": "abstain", "capability": COMPARE_TOOL}))
    proof = {"level": level, "candidate": COMPARE_TOOL, "synthetic_checks": 3, "passed": True}
    if utf16:
        proof["conversion"] = "utf16_bom_to_utf8"
    return proof
