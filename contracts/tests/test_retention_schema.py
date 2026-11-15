import pytest

from akasha_contracts.validate import validate


CONSENT = {
    "version": "1.0.0",
    "consent_id": "b3e98a2c-74c6-4d1b-93c9-2047850d7dc8",
    "project": "notes",
    "categories": ["note"],
    "purpose": "local_backup",
    "granted_at": "2026-11-15T08:00:00Z",
    "expires_at": "2026-11-22T08:00:00Z",
    "status": "active",
}

COPY = {
    "version": "1.0.0",
    "copy_id": "a66a274c-c6ce-48e6-aab3-5cc6c7df460a",
    "source_ids": ["bbedb9ab-50ee-469c-bc14-7b09f0e30d98"],
    "project": "notes",
    "category": "note",
    "retention_class": "real_content",
    "location": "backup",
    "created_at": "2026-11-15T12:00:00Z",
    "expires_at": "2026-11-22T08:00:00Z",
    "backup_id": "e39d5856-6960-4aa8-a70b-482edfc9a600",
    "backup_consent_ids": [CONSENT["consent_id"]],
}


@pytest.mark.parametrize("schema,instance", [
    ("BackupConsent", CONSENT),
    ("RetentionCopy", COPY),
])
def test_valid_retention_contract(schema, instance):
    assert validate(instance, schema) == []


@pytest.mark.parametrize("field,value", [
    ("purpose", "local_evolution"),
    ("granted_at", "2026-11-31T08:00:00Z"),
    ("expires_at", "2026-11-22T08:00:00"),
])
def test_backup_consent_requires_distinct_purpose_and_valid_instants(field, value):
    errors = validate({**CONSENT, field: value}, "BackupConsent")
    assert errors and errors[0].details["path"] == [field]


def test_backup_copy_requires_backup_identity_and_finite_expiry():
    copy = {key: value for key, value in COPY.items() if key != "backup_id"}
    errors = validate({**copy, "expires_at": None}, "RetentionCopy")
    paths = [error.details["path"] for error in errors]
    assert [] in paths
    assert ["expires_at"] in paths


def test_real_backup_copy_requires_a_consent_reference():
    copy = {key: value for key, value in COPY.items() if key != "backup_consent_ids"}
    assert validate(copy, "RetentionCopy")
