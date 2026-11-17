from dataclasses import replace
import json

import pytest

from akasha_brain import image_recovery, ocr_recovery, specialist_registry
from akasha_brain.planning import PlanningError
from akasha_brain.specialist_registry import Specialist, active_specialists, load_specialists, select_specialist
from contracts.akasha_contracts.errors import ErrorCode


def test_registered_modalities_and_contracts_are_distinct():
    expected = {
        ("conversation.intent", "intent", "conversation-intent.v1"): "communication-qwen",
        ("image.ocr", "ocr", "ocr-text.v1"): "vision-rapidocr",
        ("image.generate", "image", "verified-png.v1"): "image-sd-turbo",
        ("tasks.sql.v3", "sql", "tasks-sql-filter.v3"): "tasks-sql-v3",
        ("notes.repair_rbitnet", "code", "unified-diff.v1"): "code-rbitnet",
        ("notes.restore_reference", "solver", "verified-reference-copy.v1"): "notes-reference-solver",
        ("notes.verify", "verification", "verified-state.v1"): "notes-sqlite-verifier",
    }
    for signature, identity in expected.items():
        specialist = select_specialist(*signature)
        assert specialist.id == identity and specialist.evidence(signature[0])["engine"] == specialist.engine
    assert not any(item.fallback for item in active_specialists())
    for invalid in (("image.generate", "code", "verified-png.v1"), ("image.ocr", "ocr", "unified-diff.v1"),
                    ("notes.restore_reference", "solver", "unified-diff.v1")):
        with pytest.raises(PlanningError) as rejected:
            select_specialist(*invalid)
        assert rejected.value.error.code == ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED


def test_generalist_requires_an_explicit_decision_and_does_not_replace_nominal(monkeypatch):
    fallback = Specialist("generalist", "image", "qualified-fixture", ("image.generate",), "verified-png.v1", 8192, True)
    nominal = select_specialist("image.generate", "image", "verified-png.v1")
    monkeypatch.setattr(specialist_registry, "active_specialists", lambda: (fallback, nominal))
    assert select_specialist("image.generate", "image", "verified-png.v1", fallback_authorized=True) == nominal
    monkeypatch.setattr(specialist_registry, "active_specialists", lambda: (fallback,))
    with pytest.raises(PlanningError):
        select_specialist("image.generate", "image", "verified-png.v1")
    assert select_specialist("image.generate", "image", "verified-png.v1", fallback_authorized=True) == fallback


def test_duplicate_primaries_fail_closed(tmp_path):
    fixture = {"id": "first", "modality": "image", "engine": "sd-cpp", "capabilities": ["image.generate"],
               "contract": "verified-png.v1", "ram_mib": 8192, "fallback": False}
    catalog = tmp_path / "registry.json"
    catalog.write_text(json.dumps([fixture, {**fixture, "id": "second"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="même capacité"):
        load_specialists(catalog)


@pytest.mark.parametrize(("entry", "run"), [
    (("image.generate", "image", "verified-png.v1"), lambda: image_recovery.run(None, "", None)),
    (("image.ocr", "ocr", "ocr-text.v1"), lambda: ocr_recovery.run(None, None)),
])
def test_media_adapters_reject_an_unqualified_budget_before_starting(entry, run, monkeypatch):
    nominal = select_specialist(*entry)
    monkeypatch.setattr(specialist_registry, "active_specialists",
                        lambda: (replace(nominal, ram_mib=nominal.ram_mib + 1),))
    with pytest.raises(PlanningError) as rejected:
        run()
    assert rejected.value.error.code == ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED
