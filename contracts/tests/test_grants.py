"""Grants : acceptation dans le périmètre, refus typés hors périmètre."""

from datetime import datetime, timezone

import pytest

from akasha_contracts import authorize
from akasha_contracts.errors import ErrorCode
from akasha_contracts.grants import check_grant, record_grant_call

GRANT = {
    "grant_id": "grant-test-1",
    "provider": "local-ollama",
    "endpoint": "http://localhost:11434",
    "purpose": "profilage-phase0",
    "data_categories": ["prompt-technique"],
    "expires_at": "2030-01-01T00:00:00+00:00",
    "budget": {"max_calls": 2, "max_cost": 10.0, "calls_used": 0, "cost_used": 0.0},
    "approver": "test",
    "revoked": False,
}

CALL = {
    "purpose": "profilage-phase0",
    "data_category": "prompt-technique",
    "provider": "local-ollama",
    "endpoint": "http://localhost:11434",
}

ACTION = {"risk_class": "R3", "grant": GRANT, **CALL}


def test_appel_dans_perimetre_autorise():
    assert authorize(ACTION) is None


@pytest.mark.parametrize(("field", "value"), [
    ("provider", "autre-fournisseur"),
    ("endpoint", "http://localhost:11435"),
    ("provider", None),
    ("endpoint", None),
    ("purpose", None),
])
def test_appel_hors_perimetre_refuse_meme_si_approuve(field, value):
    err = authorize({**ACTION, field: value, "human_approval": True})
    assert err is not None and err.code == ErrorCode.GRANT_SCOPE_MISMATCH


def test_appel_distant_sans_grant_refuse_meme_si_approuve():
    err = authorize({**ACTION, "grant": None, "human_approval": True})
    assert err is not None and err.code == ErrorCode.APPROVAL_REQUIRED


def test_appel_avec_grant_sous_specifie_exige_clarification():
    err = authorize({**ACTION, "underspecified": True})
    assert err is not None and err.code == ErrorCode.NEEDS_CLARIFICATION


@pytest.mark.parametrize("expires_at", ["date-invalide", "2030-01-01T00:00:00"])
def test_expiration_invalide_produit_un_refus_type(expires_at):
    grant = {**GRANT, "expires_at": expires_at}
    err = authorize({**ACTION, "grant": grant})
    assert err is not None and err.code == ErrorCode.CONTRACT_SCHEMA_VIOLATION
    assert err.details["path"] == ["expires_at"]


def test_expire_revoque_hors_perimetre_budget():
    expired = {**GRANT, "expires_at": "2000-01-01T00:00:00+00:00"}
    assert authorize({**ACTION, "grant": expired}).code == \
        ErrorCode.GRANT_EXPIRED
    revoked = {**GRANT, "revoked": True}
    assert authorize({**ACTION, "grant": revoked}).code == \
        ErrorCode.GRANT_REVOKED
    assert authorize({**ACTION, "purpose": "autre-finalite"}).code == \
        ErrorCode.GRANT_SCOPE_MISMATCH
    assert authorize({**ACTION, "data_category": "capture-ecran"}).code == \
        ErrorCode.GRANT_SCOPE_MISMATCH
    used = record_grant_call(record_grant_call(GRANT))
    assert authorize({**ACTION, "grant": used}).code == \
        ErrorCode.GRANT_BUDGET_EXHAUSTED


def test_comptabilisation_pure():
    updated = record_grant_call(GRANT, cost=1.5)
    assert (updated["budget"]["calls_used"], updated["budget"]["cost_used"]) == (1, 1.5)
    assert GRANT["budget"]["calls_used"] == 0


def test_doute_sur_date_refuse():
    future_now = datetime(2031, 1, 1, tzinfo=timezone.utc)
    assert check_grant(GRANT, now=future_now, **CALL).code == ErrorCode.GRANT_EXPIRED
