from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from akasha_brain.evolution_consent import ReuseScope, check_reuse, grant, list_consents, revoke, timestamp
from akasha_brain.experience import transaction
from contracts.akasha_contracts.errors import ErrorCode
from contracts.akasha_contracts.validate import validate


@pytest.fixture
def consent(tmp_path):
    path = tmp_path / "journal.db"
    document = grant(path, "project-a", ["source_code"])
    scope = ReuseScope("project-a", "source_code", document["consent_id"], "project", False)
    return path, document, scope


def test_consent_matches_its_contract_and_access_covers_all_sources(consent):
    path, document, scope = consent
    assert validate({key: value for key, value in document.items() if key != "consent_id"}, "EvolutionConsent") == []
    assert list_consents(path) == [document]
    second = grant(path, "project-b", ["diffs"])
    other = ReuseScope("project-b", "diffs", second["consent_id"], "project", False)
    with transaction(path) as db:
        assert check_reuse(db, (scope,)) is None
        assert check_reuse(db, (scope, other)) is None
        denied = check_reuse(db, (scope, replace(other, consent_id=scope.consent_id)))
    assert denied.details["reason"] == "consent_scope_mismatch"


@pytest.mark.parametrize("change,code,reason", [
    ({"consent_id": None}, ErrorCode.APPROVAL_REQUIRED, "consent_missing"),
    ({"project": "project-b"}, ErrorCode.PERMISSION_DENIED, "consent_scope_mismatch"),
    ({"category": "test_outputs"}, ErrorCode.PERMISSION_DENIED, "consent_scope_mismatch"),
    ({"provenance": "transfer"}, ErrorCode.PERMISSION_DENIED, "data_excluded"),
    ({"provenance": "unknown"}, ErrorCode.PERMISSION_DENIED, "data_excluded"),
    ({"contains_secrets": True}, ErrorCode.PERMISSION_DENIED, "data_excluded"),
    ({"contains_secrets": None}, ErrorCode.PERMISSION_DENIED, "data_excluded"),
])
def test_consent_refuses_missing_or_excluded_access(consent, change, code, reason):
    path, _, scope = consent
    with transaction(path) as db:
        denied = check_reuse(db, (replace(scope, **change),))
    assert denied.code == code
    assert denied.details["reason"] == reason


def test_revocation_survives_reopening_and_new_consent_does_not_reactivate_old_scope(consent):
    path, document, scope = consent
    revoked = revoke(path, document["consent_id"])
    assert revoked["status"] == "revoked"
    assert revoke(path, document["consent_id"]) == revoked
    new_grant = grant(path, "project-a", ["source_code"])
    with transaction(path) as db:
        assert check_reuse(db, (scope,)).details["reason"] == "consent_revoked"
        assert check_reuse(db, (replace(scope, consent_id=new_grant["consent_id"]),)) is None


def test_agreement_expires_at_its_deadline(tmp_path):
    path = tmp_path / "journal.db"
    expiration = datetime.now(timezone.utc) + timedelta(days=1)
    document = grant(path, "project-a", ["source_code"], timestamp(expiration))
    scope = ReuseScope("project-a", "source_code", document["consent_id"], "project", False)
    with transaction(path) as db:
        assert check_reuse(db, (scope,), now=expiration - timedelta(seconds=1)) is None
        assert check_reuse(db, (scope,), now=expiration).details["reason"] == "consent_inactive"
