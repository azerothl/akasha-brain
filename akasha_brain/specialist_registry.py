"""Admissibilité et trace des spécialistes déclarés."""

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .planning import PlanningError

CATALOG = Path(__file__).with_name("specialists.json")
MODALITIES = {"intent", "code", "ocr", "image", "audio", "sql", "solver", "verification", "file"}


@dataclass(frozen=True)
class Specialist:
    id: str
    modality: str
    engine: str
    capabilities: tuple[str, ...]
    contract: str
    ram_mib: int
    fallback: bool

    def evidence(self, capability: str) -> dict:
        return {"specialist": self.id, "modality": self.modality, "engine": self.engine, "contract": self.contract,
                "capability": capability, "ram_mib": self.ram_mib,
                "reason": "authorized_fallback" if self.fallback else "declared_modality_contract"}


def load_specialists(catalog: Path = CATALOG) -> tuple[Specialist, ...]:
    specialists = []
    identifiers, primaries = set(), set()
    declarations = json.loads(catalog.read_bytes())
    if not isinstance(declarations, list) or not declarations:
        raise ValueError("Registre des spécialistes invalide.")
    for entry in declarations:
        if not isinstance(entry, dict) or set(entry) != set(Specialist.__annotations__):
            raise ValueError("Registre des spécialistes invalide.")
        if (not all(isinstance(entry[key], str) and entry[key] for key in ("id", "engine", "contract", "modality"))
                or entry["id"] in identifiers or entry["modality"] not in MODALITIES
                or type(entry["ram_mib"]) is not int or entry["ram_mib"] < 0 or type(entry["fallback"]) is not bool):
            raise ValueError("Déclaration de spécialiste invalide.")
        capabilities = entry["capabilities"]
        if (not isinstance(capabilities, list) or not capabilities
                or not all(isinstance(name, str) and name for name in capabilities)
                or len(set(capabilities)) != len(capabilities)):
            raise ValueError("Capacités du spécialiste invalides.")
        if not entry["fallback"] and primaries.intersection(capabilities):
            raise ValueError("Deux spécialistes principaux déclarent la même capacité.")
        identifiers.add(entry["id"])
        if not entry["fallback"]:
            primaries.update(capabilities)
        specialists.append(Specialist(**{**entry, "capabilities": tuple(capabilities)}))
    return tuple(specialists)


@lru_cache(maxsize=1)
def active_specialists() -> tuple[Specialist, ...]:
    return load_specialists()


def select_specialist(capability: str, modality: str, contract: str, *, fallback_authorized=False) -> Specialist:
    eligible = tuple(item for item in active_specialists() if capability in item.capabilities
                     and item.modality == modality and item.contract == contract)
    nominal = next((item for item in eligible if not item.fallback), None)
    if nominal is not None:
        return nominal
    if fallback_authorized is True:
        fallback = next((item for item in eligible if item.fallback), None)
        if fallback is not None:
            return fallback
    raise PlanningError(AkashaError(ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED,
        "Aucun spécialiste compatible avec la modalité et le contrat demandés.",
        {"capability": capability, "modality": modality}))


def require_specialist(capability: str, modality: str, contract: str, engine: str, *,
                       ram_mib: int | None = None, fallback_authorized=False) -> Specialist:
    specialist = select_specialist(capability, modality, contract, fallback_authorized=fallback_authorized)
    if specialist.engine != engine or (ram_mib is not None and specialist.ram_mib != ram_mib):
        raise PlanningError(AkashaError(ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED,
            "Le moteur ou son budget diffère de l’adaptateur qualifié.",
            {"capability": capability, "modality": modality}))
    return specialist
