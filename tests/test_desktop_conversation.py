from akasha_brain.desktop_conversation import result_summary, route_request


def test_conversation_routes_to_known_flows_and_clarifies_other_requests():
    assert route_request("Pouvez-vous réparer les Notes ?") == "notes"
    assert route_request("Prépare une proposition pour mon projet.") == "project"
    assert route_request("Affiche le verdict du projet.") == "review"
    assert route_request("Quel est le résultat Notes ?") == "result"
    assert route_request("Je veux modifier quelque chose.") is None
    assert route_request("Lance le transfert de Tâches.") is None


def test_conversation_summarizes_only_observed_tests_and_persistence():
    report = {"status": "passed", "wall_s": 106.902, "trace": [
        {"id": "verify", "status": "passed", "result": {"tests": 4, "passed": 4, "sqlite_verdict": "passed"}},
        {"id": "verify_desktop", "status": "passed"},
    ]}
    text, facts = result_summary(report)
    assert facts == (4, 4, "106,9")
    assert "SQLite a confirmé" in text and "RapidOCR a retrouvé" in text
    assert result_summary({**report, "status": "failed"})[1] is None
