"""Validateur : exemples valides acceptés, violations typées avec chemin."""

from akasha_contracts.errors import ErrorCode
from akasha_contracts.validate import check_semver_exact, validate

GOAL = {
    "goal_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_intent": "Corriger la sauvegarde des notes",
    "success_conditions": [
        {"predicate": "test_suite_passes", "on": "CodeState",
         "args": {"command": "pytest -q"}}
    ],
    "risk_class": "R1",
}


def test_goal_valide():
    assert validate(GOAL, "GoalSpec") == []


def test_risk_class_inconnue_rejetee_avec_chemin():
    bad = {**GOAL, "risk_class": "R9"}
    errors = validate(bad, "GoalSpec")
    assert len(errors) == 1
    assert errors[0].code == ErrorCode.CONTRACT_SCHEMA_VIOLATION
    assert errors[0].family == "contrat"
    assert errors[0].details["path"] == ["risk_class"]


def test_predicat_hors_ensemble_ferme_rejete():
    bad = {**GOAL, "success_conditions": [
        {"predicate": "llm_judge_ok", "on": "CodeState", "args": {}}]}
    errors = validate(bad, "GoalSpec")
    assert errors and errors[0].code == ErrorCode.CONTRACT_SCHEMA_VIOLATION


def test_profondeur_bornee_acceptee_et_imbrication_refusee():
    ok = {"all_of": [
        {"predicate": "file_exists", "on": "CodeState", "args": {"path": "x.py"}}]}
    assert validate(ok, "SuccessPredicate") == []
    nested = {"all_of": [{"all_of": [
        {"predicate": "file_exists", "on": "CodeState", "args": {"path": "x.py"}}]}]}
    assert validate(nested, "SuccessPredicate")


def test_schema_inconnu_typé():
    errors = validate({}, "Inexistant", "v9.9.9")
    assert len(errors) == 1
    assert errors[0].code == ErrorCode.CONTRACT_VERSION_UNKNOWN
    assert errors[0].family == "contrat"


def test_semver_exacte_exigee():
    assert check_semver_exact("1.0.0", "manifest") is None
    err = check_semver_exact("^1.0.0", "manifest")
    assert err is not None and err.code == ErrorCode.CONTRACT_SEMVER_RANGE
    err = check_semver_exact("1.0", "manifest")
    assert err is not None and err.code == ErrorCode.CONTRACT_SEMVER_RANGE
