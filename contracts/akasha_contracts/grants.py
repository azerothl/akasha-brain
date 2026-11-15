"""Vérification des grants d'inférence distante (spec §13.7).

Refus par défaut en cas de doute. Avant exécution, vérifier la destination,
la finalité, les catégories, l'expiration, le budget et la révocation.
L'audit exclut le prompt, la réponse et leur empreinte.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .errors import AkashaError, ErrorCode
from .validate import validate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_grant(grant: dict, purpose: str | None, data_category: str | None,
                now: datetime | None = None, *, provider: str | None = None,
                endpoint: str | None = None) -> AkashaError | None:
    """Autorise l'appel si sa destination effective et son usage sont couverts."""
    errors = validate(grant, "RemoteInferenceGrant")
    if errors:
        err = errors[0]
        return AkashaError(ErrorCode.CONTRACT_SCHEMA_VIOLATION, err.message, err.details)
    moment = now or _now()
    if grant.get("revoked"):
        return AkashaError(ErrorCode.GRANT_REVOKED,
                           f"Grant {grant['grant_id']} révoqué.", {"grant_id": grant["grant_id"]})
    try:
        expires_at = datetime.fromisoformat(grant["expires_at"])
    except ValueError:
        expires_at = None
    if expires_at is None or expires_at.tzinfo is None:
        return AkashaError(ErrorCode.CONTRACT_SCHEMA_VIOLATION,
                           "Le champ expires_at doit être un horodatage ISO 8601 avec décalage UTC.",
                           {"schema": "RemoteInferenceGrant", "path": ["expires_at"]})
    if moment >= expires_at:
        return AkashaError(ErrorCode.GRANT_EXPIRED,
                           f"Grant {grant['grant_id']} expiré.", {"grant_id": grant["grant_id"]})
    if (provider != grant["provider"] or endpoint != grant["endpoint"]
            or purpose != grant["purpose"] or data_category not in grant["data_categories"]):
        return AkashaError(ErrorCode.GRANT_SCOPE_MISMATCH,
                           "Destination, finalité ou catégorie hors périmètre du grant.",
                           {"grant_id": grant["grant_id"]})
    budget = grant.get("budget", {})
    if ("max_calls" in budget and budget.get("calls_used", 0) >= budget["max_calls"]
            or "max_cost" in budget and budget.get("cost_used", 0) >= budget["max_cost"]):
        return AkashaError(ErrorCode.GRANT_BUDGET_EXHAUSTED,
                           f"Budget du grant {grant['grant_id']} épuisé.",
                           {"grant_id": grant["grant_id"]})
    return None


def record_grant_call(grant: dict, cost: float = 0.0) -> dict:
    """Retourne une copie du grant avec le compteur d'appels (et coût) avancé."""
    updated = {**grant, "budget": {**grant.get("budget", {})}}
    updated["budget"]["calls_used"] = updated["budget"].get("calls_used", 0) + 1
    updated["budget"]["cost_used"] = updated["budget"].get("cost_used", 0) + cost
    return updated
