"""Grants : acceptation dans le périmètre, refus typés hors périmètre."""

from datetime import datetime, timezone

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


def test_appel_dans_perimetre_autorise():
    assert check_grant(GRANT, "profilage-phase0", "prompt-technique") is None


def test_expire_revoque_hors_perimetre_budget():
    expired = {**GRANT, "expires_at": "2000-01-01T00:00:00+00:00"}
    assert check_grant(expired, "profilage-phase0", "prompt-technique").code == \
        ErrorCode.GRANT_EXPIRED
    revoked = {**GRANT, "revoked": True}
    assert check_grant(revoked, "profilage-phase0", "prompt-technique").code == \
        ErrorCode.GRANT_REVOKED
    assert check_grant(GRANT, "autre-finalite", "prompt-technique").code == \
        ErrorCode.GRANT_SCOPE_MISMATCH
    assert check_grant(GRANT, "profilage-phase0", "capture-ecran").code == \
        ErrorCode.GRANT_SCOPE_MISMATCH
    used = record_grant_call(record_grant_call(GRANT))
    assert check_grant(used, "profilage-phase0", "prompt-technique").code == \
        ErrorCode.GRANT_BUDGET_EXHAUSTED


def test_comptabilisation_pure():
    updated = record_grant_call(GRANT, cost=1.5)
    assert (updated["budget"]["calls_used"], updated["budget"]["cost_used"]) == (1, 1.5)
    assert GRANT["budget"]["calls_used"] == 0


def test_doute_sur_date_refuse():
    future_now = datetime(2031, 1, 1, tzinfo=timezone.utc)
    assert check_grant(GRANT, "profilage-phase0", "prompt-technique",
                       now=future_now).code == ErrorCode.GRANT_EXPIRED
