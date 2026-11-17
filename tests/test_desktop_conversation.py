import pytest

from akasha_brain.desktop_conversation import TextChange, parse_project_check, parse_replacement, result_summary, route_request
from akasha_brain.project_check import inspect_project, run_project_check


def test_conversation_routes_to_known_flows_and_clarifies_other_requests():
    assert route_request("Pouvez-vous réparer les Notes ?") == "notes"
    assert route_request("Prépare une proposition pour mon projet.") == "project"
    assert route_request("Affiche le verdict du projet.") == "review"
    assert route_request("Montre le diff") == "diff"
    assert route_request("Quel est le résultat Notes ?") == "result"
    assert route_request("Je veux modifier quelque chose.") is None
    assert route_request("Lance le transfert de Tâches.") is None


def test_capability_question_and_exclusion_do_not_offer_the_notes_bench():
    assert route_request("qu'est ce que tu peux faire ?") == "capabilities"
    assert route_request("mis a part lancer notes ?") == "project_capabilities"
    assert route_request("Ne lance pas Notes") is None


def test_project_replacement_keeps_the_exact_text_and_relative_path():
    assert parse_replacement('Remplace «  ancien » par « nouveau » dans "src/un fichier.py"') == TextChange(
        "src/un fichier.py", "  ancien ", " nouveau "
    )
    assert parse_replacement("Change le port de configuration") is None


def test_project_check_accepts_a_path_from_a_normal_question():
    assert parse_project_check(r"tu peux vérifier ce projet D:\dev\documentalist ?") == r"D:\dev\documentalist"
    assert parse_project_check(r'Peux-tu examiner le dossier "D:\Mes Dépôts\Mon projet" ?') == r"D:\Mes Dépôts\Mon projet"
    assert parse_project_check("Vérifie ce projet") == ""
    assert parse_project_check(r"D:\Mes Dépôts\Mon projet") == r"D:\Mes Dépôts\Mon projet"
    assert parse_project_check("Vérifie le banc Notes") is None
    assert parse_project_check(r"Ne vérifie pas ce projet D:\dev\documentalist") is None


def test_project_check_detects_errors_without_executing_project_code(tmp_path):
    (tmp_path / "check.py").write_text("raise RuntimeError('executed')\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"scripts":{"test":"exit 1"}}', encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignore.py").write_text("invalid syntax\n", encoding="utf-8")
    check = inspect_project(tmp_path)
    assert set(check.python_hashes) == {"check.py"}
    assert check.test.label == "check.py"
    assert "Un script npm test est déclaré" in check.summary()
    (tmp_path / "broken.py").write_text("return 3\n", encoding="utf-8")
    check = inspect_project(tmp_path)
    assert check.test is None
    assert "Syntaxe Python invalide dans broken.py, ligne 1" in check.summary()


def test_project_check_refuses_to_run_sources_changed_after_inspection(tmp_path):
    entry = tmp_path / "check.py"
    entry.write_text("assert 1\n", encoding="utf-8")
    check = inspect_project(tmp_path)
    entry.write_text("assert 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Les sources ont changé"):
        run_project_check(check, tmp_path / "unused-runtime")


def test_conversation_summarizes_only_observed_tests_and_persistence():
    report = {"status": "passed", "wall_s": 106.902, "trace": [
        {"id": "verify", "status": "passed", "result": {"tests": 4, "passed": 4, "sqlite_verdict": "passed"}},
        {"id": "verify_desktop", "status": "passed"},
    ]}
    text, facts = result_summary(report)
    assert facts == (4, 4, "106,9")
    assert "SQLite a confirmé" in text and "RapidOCR a retrouvé" in text
    assert result_summary({**report, "status": "failed"})[1] is None
