"""Erreurs typées stables (spec §6, §14, §5.1, §6.2).

Familles : contrat, capacité, permission, ressource, environnement, délai,
incertitude. Chaque erreur porte un code stable, sa famille et un message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ErrorCode(str, Enum):
    # Contrat (§6, §14)
    CONTRACT_SCHEMA_VIOLATION = "contract_schema_violation"
    CONTRACT_VERSION_UNKNOWN = "contract_version_unknown"
    CONTRACT_SEMVER_RANGE = "contract_semver_range"
    CONTRACT_PREDICATE_UNKNOWN = "contract_predicate_unknown"
    CONTRACT_PREDICATE_DEPTH = "contract_predicate_depth"
    CONTRACT_PRECONDITION_FAILED = "contract_precondition_failed"
    CONTRACT_POSTCONDITION_FAILED = "contract_postcondition_failed"
    # Capacité (§14, §6.2)
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CAPABILITY_ENGINE_UNSUPPORTED = "capability_engine_unsupported"
    RESIDENCY_UNAVAILABLE = "residency_unavailable"
    # Permission (§13, §13.6-13.7)
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_REQUIRED = "approval_required"
    GRANT_EXPIRED = "grant_expired"
    GRANT_REVOKED = "grant_revoked"
    GRANT_SCOPE_MISMATCH = "grant_scope_mismatch"
    GRANT_BUDGET_EXHAUSTED = "grant_budget_exhausted"
    # Ressource (§6.2, §15.1)
    RESOURCE_BUDGET_EXCEEDED = "resource_budget_exceeded"
    # Environnement (§9.7, §12)
    ENVIRONMENT_OBSERVATION_FAILED = "environment_observation_failed"
    # Délai (§8.4, §14)
    APPROVAL_EXPIRED = "approval_expired"
    TIMEOUT_EXCEEDED = "timeout_exceeded"
    # Incertitude (§5.1, §5.4)
    NEEDS_CLARIFICATION = "needs_clarification"
    PREDICATE_EVALUATOR_UNAVAILABLE = "predicate_evaluator_unavailable"
    HUMAN_CONFIRM_PENDING = "human_confirm_pending"


FAMILY: dict[ErrorCode, str] = {
    ErrorCode.CONTRACT_SCHEMA_VIOLATION: "contrat",
    ErrorCode.CONTRACT_VERSION_UNKNOWN: "contrat",
    ErrorCode.CONTRACT_SEMVER_RANGE: "contrat",
    ErrorCode.CONTRACT_PREDICATE_UNKNOWN: "contrat",
    ErrorCode.CONTRACT_PREDICATE_DEPTH: "contrat",
    ErrorCode.CONTRACT_PRECONDITION_FAILED: "contrat",
    ErrorCode.CONTRACT_POSTCONDITION_FAILED: "contrat",
    ErrorCode.CAPABILITY_UNAVAILABLE: "capacité",
    ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED: "capacité",
    ErrorCode.RESIDENCY_UNAVAILABLE: "capacité",
    ErrorCode.PERMISSION_DENIED: "permission",
    ErrorCode.APPROVAL_REQUIRED: "permission",
    ErrorCode.GRANT_EXPIRED: "permission",
    ErrorCode.GRANT_REVOKED: "permission",
    ErrorCode.GRANT_SCOPE_MISMATCH: "permission",
    ErrorCode.GRANT_BUDGET_EXHAUSTED: "permission",
    ErrorCode.RESOURCE_BUDGET_EXCEEDED: "ressource",
    ErrorCode.ENVIRONMENT_OBSERVATION_FAILED: "environnement",
    ErrorCode.APPROVAL_EXPIRED: "délai",
    ErrorCode.TIMEOUT_EXCEEDED: "délai",
    ErrorCode.NEEDS_CLARIFICATION: "incertitude",
    ErrorCode.PREDICATE_EVALUATOR_UNAVAILABLE: "incertitude",
    ErrorCode.HUMAN_CONFIRM_PENDING: "incertitude",
}


@dataclass(frozen=True)
class AkashaError:
    """Erreur typée : code stable, famille dérivée, message, détails."""

    code: ErrorCode
    message: str
    details: dict = field(default_factory=dict)

    @property
    def family(self) -> str:
        return FAMILY[self.code]

    def as_dict(self) -> dict:
        return {"code": self.code.value, "family": self.family,
                "message": self.message, "details": self.details}
