import pytest

from akasha_brain import conversation_planning
from akasha_brain.conversation_planning import (
    compare_documents, compile_local_plan, decode_intents, execute_intents, infer_intent, intent_parts,
    load_conversation_catalog,
    plan_intent, references, refines_project_summary,
)
from akasha_brain.planning import PlanningError
from akasha_brain.project_check import inspect_project
from contracts.akasha_contracts.errors import ErrorCode


def test_plan_targets_only_references_named_in_the_request(tmp_path):
    assert references(r'Veux-tu examiner « D:\Mes dépôts\Exemple (test) » ?') == [r"D:\Mes dépôts\Exemple (test)"]
    for name in ("ancienne version.md", "nouvelle version.md"):
        (tmp_path / name).write_text(name + "\n", encoding="utf-8")
    request = "Qu’a-t-on changé entre « ancienne version.md » et « nouvelle version.md » ?"
    refs = references(request)
    catalog = load_conversation_catalog()
    plan = plan_intent(request, {"tool": "documents.compare", "refs": [1, 2], "detail": ""}, refs, tmp_path, catalog)
    assert plan.goal["risk_class"] == "R0"
    assert plan.goal["constraints"]["allowed_actions"] == ["documents.compare"]
    assert "-ancienne version.md\n+nouvelle version.md" in compare_documents(tmp_path, plan.inputs)
    with pytest.raises(PlanningError) as missing_ref:
        plan_intent(request, {"tool": "documents.compare", "refs": [1, 3], "detail": ""}, refs, tmp_path, catalog)
    assert missing_ref.value.error.code == ErrorCode.NEEDS_CLARIFICATION


def test_outside_scope_and_unavailable_capability_are_typed(tmp_path):
    catalog = load_conversation_catalog()
    with pytest.raises(PlanningError) as outside:
        plan_intent("Lis ce fichier", {"tool": "file.read", "refs": [1], "detail": ""},
                    [str(tmp_path.parent / "other.md")], tmp_path, catalog)
    assert outside.value.error.code == ErrorCode.PERMISSION_DENIED
    with pytest.raises(PlanningError) as unavailable:
        plan_intent("Crée un rendez-vous", {"tool": "missing", "refs": [], "detail": "calendrier"}, [], tmp_path, catalog)
    assert unavailable.value.error.code == ErrorCode.CAPABILITY_UNAVAILABLE
    assert "calendrier" in str(unavailable.value)


def test_node_plan_preserves_confirmation_and_ignores_npm_lifecycle_commands(tmp_path):
    (tmp_path / "test.js").write_text("// fixture\n", encoding="utf-8")
    package = tmp_path / "package.json"
    package.write_text('{"scripts":{"test":"node --test && echo unsafe"}}', encoding="utf-8")
    assert inspect_project(tmp_path).test is None
    package.write_text('{"scripts":{"pretest":"echo unsafe","test":"node --test"}}', encoding="utf-8")
    test = inspect_project(tmp_path).test
    assert test and test.files == ("test.js",)
    catalog = load_conversation_catalog()
    plan = compile_local_plan("Lancer les tests", "project.test.node", (str(tmp_path), *test.files), catalog, test=True)
    assert plan.goal["approval_requirements"] == ["confirm-sandbox-test"]
    assert plan.goal["constraints"]["environment_id"] == "windows-sandbox"
    with pytest.raises(PlanningError):
        plan_intent("Lance une commande", {"tool": "project.test.node", "refs": [], "detail": ""}, [], tmp_path, catalog)


def test_combined_project_check_and_summary_report_each_result(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Atlas\n\nAtlas organise les documents par projet et permet de retrouver leur historique.\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"19"},"scripts":{"test":"vitest run"}}',
                                         encoding="utf-8")
    request = f"verifie le projet « {tmp_path} » et fais moi un résumé de celui ci"
    assert intent_parts(request) == [f"verifie le projet « {tmp_path} »", "fais moi un résumé de celui ci"]
    catalog = load_conversation_catalog()
    proposed = infer_intent(None, "", request, references(request), catalog, selected=False)
    check, summary = execute_intents(request, proposed, references(request), None, catalog)
    assert check.plan.capability == "project.inspect" and check.output.test is None
    assert "Tests non exécutés" in check.output.summary() and "autre lanceur" in check.output.summary()
    assert summary.plan.capability == "project.summarize"
    assert "Atlas organise les documents" in summary.output and "README.md" in summary.output
    assert "Bibliothèques déclarées · react" in summary.output


def test_missing_tool_does_not_discard_an_independent_result(tmp_path):
    request = "Présente le dépôt, puis publie le résumé dans la messagerie."
    proposed = [{"tool": "project.summarize", "refs": [], "detail": ""},
                {"tool": "missing", "refs": [], "detail": "outil de messagerie"}]
    summary, missing = execute_intents(request, proposed, [], tmp_path, load_conversation_catalog())
    assert summary.plan.capability == "project.summarize" and "ne décrivent pas le rôle" in summary.output
    assert missing.code == ErrorCode.CAPABILITY_UNAVAILABLE and "outil de messagerie" in missing.message


def test_intent_does_not_split_quoted_names_and_validates_the_json_tail():
    assert intent_parts('Compare « Préparer puis relire.md » et « Version 2.md »') == [
        'Compare « Préparer puis relire.md » et « Version 2.md »'
    ]
    assert decode_intents('[{"tool":"missing","refs":[],"detail":"outil mail"}]]')[0]["tool"] == "missing"
    with pytest.raises(ValueError):
        decode_intents('[] [{"tool":"file.read","refs":[1],"detail":""}]')


def test_summary_refinement_reads_details_beyond_the_introduction(tmp_path):
    tmp_path = tmp_path / "resume-detaille-atlas"
    tmp_path.mkdir()
    (tmp_path / "README.md").write_text(
        "# Atlas\n\nAtlas classe les documents de travail par espace.\n\n"
        "## Fonctionnalités\n\n| Fonction | Usage |\n| --- | --- |\n| Portail | Publication sélective |\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("# Architecture\n\nUn index SQLite conserve les métadonnées et les versions.\n",
                                          encoding="utf-8")
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"19"},"scripts":{"test":"vitest run"}}',
                                         encoding="utf-8")
    catalog = load_conversation_catalog()
    proposed = {"tool": "project.summarize", "refs": [], "detail": ""}
    first_request = f"Résume le projet « {tmp_path} »"
    overview, = execute_intents(first_request, proposed, references(first_request), None, catalog)
    request = "fais moi un résumé plus complet"
    detailed, = execute_intents(request, proposed, [], tmp_path, catalog)
    assert detailed.routing["specialist"] == "project-local-tools"
    assert detailed.routing["ram_mib"] == 0
    assert refines_project_summary(request) and refines_project_summary("Approfondis")
    assert not refines_project_summary('Fais-moi un résumé plus complet de « autre.md »')
    assert not refines_project_summary("Envoie un résumé plus complet par courriel")
    assert overview.plan.goal["constraints"]["summary_depth"] == "overview"
    assert detailed.plan.goal["constraints"]["summary_depth"] == "detailed"
    assert "SQLite" not in overview.output and "Publication sélective" not in overview.output
    assert "Publication sélective [README.md · Fonctionnalités]" in detailed.output
    assert "Un index SQLite" in detailed.output and "[docs/architecture.md · Architecture]" in detailed.output
    assert "Scripts déclarés dans package.json · test" in detailed.output


def test_catalog_cache_preserves_input_validation_and_isolation(tmp_path, monkeypatch):
    path = tmp_path / "conversation-capabilities.json"
    path.write_bytes(conversation_planning.REGISTRY.read_bytes())
    monkeypatch.setattr(conversation_planning, "REGISTRY", path)
    first = load_conversation_catalog()
    first["file.read"]["permissions"].clear()
    assert load_conversation_catalog()["file.read"]["permissions"]
    path.write_bytes(b"[{}]")
    with pytest.raises(PlanningError):
        load_conversation_catalog()
