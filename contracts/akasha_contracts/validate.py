"""Validateur d'entrée/sortie du runtime (spec §6, §6.1, §16.1).

Valide une instance contre un schéma gelé et convertit chaque violation en
erreur typée. Le runtime tolère les champs inconnus en entrée et conserve les
parseurs des majeurs supportés ; la fenêtre de support est fixée à un seul
majeur (le courant) avant le gel Phase 0 (spec §16.1).
"""

from __future__ import annotations

import json
import os
import re

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .errors import AkashaError, ErrorCode

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas")

# Majeurs supportés par schéma : fenêtre de support = majeur courant seul.
SUPPORTED_MAJOR: dict[str, int] = {
    "GoalSpec": 1,
    "SuccessPredicate": 1,
    "CapabilityManifest": 1,
    "ArtifactEnvelope": 1,
    "ExperienceRecord": 1,
    "RemoteInferenceGrant": 1,
    "RetentionPolicy": 1,
    "EvolutionConsent": 1,
}

_SEMVER_EXACT = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SEMVER_RANGE = re.compile(r"[\^~<>=x*]")

_cache: dict[str, dict] = {}
_registry: Registry | None = None


def _get_registry() -> Registry:
    """Registre local : chaque $id gelé résout vers son fichier (aucun réseau)."""
    global _registry
    if _registry is None:
        pairs = []
        for root, _dirs, files in os.walk(SCHEMA_DIR):
            for filename in sorted(files):
                if filename.endswith(".json"):
                    with open(os.path.join(root, filename), encoding="utf-8") as fh:
                        doc = json.load(fh)
                    pairs.append((doc["$id"], Resource(contents=doc,
                                                         specification=DRAFT202012)))
        _registry = Registry().with_resources(pairs)
    return _registry


def load_schema(name: str, version: str = "v1.0.0") -> dict:
    """Charge un schéma gelé. Version inconnue = erreur typée."""
    key = f"{name}/{version}"
    if key not in _cache:
        path = os.path.join(SCHEMA_DIR, name, f"{version}.json")
        if not os.path.isfile(path):
            raise _as_exception(AkashaError(
                ErrorCode.CONTRACT_VERSION_UNKNOWN,
                f"Schéma inconnu : {key}.",
                {"schema": name, "version": version},
            ))
        with open(path, encoding="utf-8") as fh:
            _cache[key] = json.load(fh)
    return _cache[key]


def validate(instance: object, schema_name: str,
             version: str = "v1.0.0") -> list[AkashaError]:
    """Valide `instance`. Retourne la liste des erreurs (vide = valide)."""
    try:
        schema = load_schema(schema_name, version)
    except _ValidationInternal as exc:
        return [exc.error]

    major = int(version.lstrip("v").split(".")[0])
    if major != SUPPORTED_MAJOR.get(schema_name, major):
        return [AkashaError(
            ErrorCode.CONTRACT_VERSION_UNKNOWN,
            f"Majeur {major} de {schema_name} hors fenêtre de support.",
            {"schema": schema_name, "version": version},
        )]

    validator = Draft202012Validator(schema, registry=_get_registry())
    errors: list[AkashaError] = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        errors.append(AkashaError(
            ErrorCode.CONTRACT_SCHEMA_VIOLATION,
            f"{schema_name} : {'/'.join(str(p) for p in err.absolute_path) or '(racine)'} — {err.message}",
            {"schema": schema_name, "version": version,
             "path": list(err.absolute_path)},
        ))
    return errors


def check_semver_exact(value: str, where: str) -> AkashaError | None:
    """Refuse les plages SemVer (spec §6.1 : version exacte exigée)."""
    if not isinstance(value, str) or not _SEMVER_EXACT.match(value):
        return AkashaError(
            ErrorCode.CONTRACT_SEMVER_RANGE,
            f"{where} : version non exacte {value!r} (plages interdites).",
            {"where": where, "value": value},
        )
    return None


class _ValidationInternal(Exception):
    def __init__(self, error: AkashaError) -> None:
        super().__init__(error.message)
        self.error = error


def _as_exception(error: AkashaError) -> _ValidationInternal:
    return _ValidationInternal(error)
