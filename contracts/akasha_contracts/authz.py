"""Autorisation hors modèle (spec §13.5.1, §13.6, §13.7).

Décision structurelle depuis les classes d'actions déclarées, jamais depuis
un jugement de modèle. Refus par défaut en cas de doute ; classe inconnue
vaut R3. `None` = autorisé, sinon l'erreur typée du refus.
"""

from __future__ import annotations

from .errors import AkashaError, ErrorCode
from .grants import check_grant

ALLOW = None


def authorize(action: dict) -> AkashaError | None:
    """Autorise ou refuse une action. Champs lus : voir `_read`."""
    risk, confinement, approval, underspecified, grant, purpose, category = _read(action)

    if risk == "R3" or risk not in ("R0", "R1", "R2"):
        if grant is not None and purpose is not None and risk == "R3":
            grant_err = check_grant(grant, purpose, category or "")
            return grant_err
        if approval is True and risk == "R3":
            return ALLOW
        return AkashaError(ErrorCode.APPROVAL_REQUIRED,
                           "Action R3 : approbation humaine obligatoire.",
                           {"risk_class": risk or "unknown"})
    if risk == "R0":
        return ALLOW
    if underspecified and risk in ("R2",):
        return AkashaError(ErrorCode.NEEDS_CLARIFICATION,
                           "Objectif sous-spécifié : aucune action R2/R3 avant clarification.",
                           {"risk_class": risk})
    if risk == "R2":
        if approval is True:
            return ALLOW
        return AkashaError(ErrorCode.APPROVAL_REQUIRED,
                           "Action R2 : approbation par défaut en Phase 0-1.",
                           {"risk_class": risk})
    # R1 : effet borné et réversible, uniquement si le confinement est vérifié.
    if confinement is True:
        return ALLOW
    return AkashaError(ErrorCode.PERMISSION_DENIED,
                       "Action R1 hors confinement vérifié : refusée.",
                       {"risk_class": risk})


def escalate(risk: str | None, destructive_hint: bool) -> str:
    """`destructiveHint=true` vaut au minimum R2 (spec §13.6)."""
    if destructive_hint and risk in (None, "R0", "R1"):
        return "R2"
    return risk or "R3"


def _read(action: dict) -> tuple:
    return (
        action.get("risk_class"),
        action.get("confinement_verified"),
        action.get("human_approval"),
        action.get("underspecified", False),
        action.get("grant"),
        action.get("purpose"),
        action.get("data_category"),
    )
