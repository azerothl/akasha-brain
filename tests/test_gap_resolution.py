import json
import sqlite3

import pytest

from contracts.akasha_contracts.errors import ErrorCode

from akasha_brain import conversation_planning
from akasha_brain.capability_recovery import Recovery
from akasha_brain.conversation_planning import execute_intents, load_conversation_catalog, references
from akasha_brain.gap_resolution import GapReview
from akasha_brain.planning import PlanningError

MISSING = {"tool": "missing", "refs": [], "detail": "adaptateur local"}


def recovery(root):
    return Recovery(root / "recovery.sqlite", None, lambda _: None, lambda: False)


def execute(state, request, project, intent=MISSING, catalog=None):
    return execute_intents(request, intent, references(request), project, catalog or load_conversation_catalog(),
                           recovery=state)[0]


def test_comparison_recomposition_is_replayed_before_use(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "avant.md").write_text("Ligne A\n", encoding="utf-8")
    (project / "apres.md").write_text("Ligne B\n", encoding="utf-8")
    state = recovery(tmp_path)
    request = "Compare « avant.md » et « apres.md »."
    result = execute(state, request, project)
    assert result.plan.capability == "documents.compare"
    assert result.output.endswith("-Ligne A\n+Ligne B\n")
    assert result.diagnostic == {"level": "A", "candidate": "documents.compare", "synthetic_checks": 3, "passed": True}
    with sqlite3.connect(state.database) as db:
        report, = db.execute("SELECT report FROM gap_reports WHERE capability = 'documents.compare'").fetchone()
        assert not db.execute("SELECT 1 FROM local_capabilities").fetchone()
    assert json.loads(report)["status"] == "resumed"
    assert request not in report and "Ligne A" not in report


def test_failed_recomposition_abstains_and_does_not_touch_real_inputs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    for name in ("avant.md", "apres.md"):
        (project / name).touch()
    calls = []

    def broken_compare(root, inputs):
        calls.append(root)
        return "comparaison non vérifiée"

    monkeypatch.setattr(conversation_planning, "compare_documents", broken_compare)
    result = execute(recovery(tmp_path), "Compare « avant.md » et « apres.md ».", project)
    assert result.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED and result.details["outcome"] == "abstain"
    assert len(calls) == 2 and all(path != project for path in calls)


def test_utf16_link_conversion_is_replayed_and_never_writes_to_documents(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    before = "Ligne avant\n".encode("utf-16")
    after = "Ligne après\n".encode("utf-8")
    (project / "avant.txt").write_bytes(before)
    (project / "apres.txt").write_bytes(after)
    state = recovery(tmp_path)
    requested = {"tool": "documents.compare", "refs": [1, 2], "detail": ""}
    result = execute(state, "Compare avant.txt et apres.txt", project, requested)
    assert result.output.endswith("-Ligne avant\n+Ligne après\n")
    assert result.diagnostic == {"level": "B", "candidate": "documents.compare", "synthetic_checks": 3,
                                 "passed": True, "conversion": "utf16_bom_to_utf8"}
    assert (project / "avant.txt").read_bytes() == before
    assert (project / "apres.txt").read_bytes() == after


@pytest.mark.parametrize(("data", "outcome"), [
    ("-----BEGIN PRIVATE KEY-----\nsynthetic\n".encode("utf-16"), "denied"),
    ("Ligne UTF-32".encode("utf-32"), "missing"),
    ("Document\0sur deux octets".encode("utf-16"), "missing"),
    (b"\xff\xfe\xff", "missing"),
])
def test_utf16_link_rechecks_permissions_and_rejects_other_encodings(tmp_path, data, outcome):
    project = tmp_path / "project"
    project.mkdir()
    (project / "avant.txt").write_bytes(data)
    (project / "apres.txt").write_text("Texte public", encoding="utf-8")
    state = recovery(tmp_path)
    answer = execute(state, "Compare avant.txt et apres.txt", project)
    assert answer.details["outcome"] == outcome


@pytest.mark.parametrize("first", [MISSING, {"tool": "file.read", "refs": [1], "detail": ""}])
def test_read_compare_skill_keeps_order_and_stays_in_candidate_registry(tmp_path, first):
    project = tmp_path / "project"
    project.mkdir()
    (project / "avant.md").write_text("Accès ancien\n", encoding="utf-8")
    (project / "apres.md").write_text("Accès nouveau\n", encoding="utf-8")
    state = recovery(tmp_path)
    request = "Lis « avant.md » puis compare « avant.md » et « apres.md »."
    read, compare = execute_intents(request, [first, MISSING], references(request), project,
                                    load_conversation_catalog(), recovery=state)
    assert read.plan.capability == "file.read" and compare.plan.capability == "documents.compare"
    assert read.output["lines"][0]["text"] == "Accès ancien"
    assert compare.output.endswith("-Accès ancien\n+Accès nouveau\n")
    proof = read.diagnostic
    assert proof == compare.diagnostic and proof["level"] == "C" and proof["passed"]
    assert [node["depends_on"] for node in proof["graph"]] == [[], [0]]
    with sqlite3.connect(state.database) as db:
        serialized, = db.execute("SELECT report FROM gap_reports WHERE capability = ?", (proof["candidate"],)).fetchone()
        assert not db.execute("SELECT 1 FROM local_capabilities").fetchone()
    assert json.loads(serialized)["status"] == "candidate_evaluated"
    assert "avant.md" not in serialized and "Accès ancien" not in serialized


def test_read_compare_skill_stops_before_next_step_when_the_read_fails(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "avant.md").write_text("-----BEGIN PRIVATE KEY-----\nsynthetic\n", encoding="utf-8")
    (project / "apres.md").write_text("Nouveau contenu", encoding="utf-8")
    request = "Lis avant.md puis compare avant.md et apres.md"
    state = recovery(tmp_path)
    failure, = execute_intents(request, [MISSING, MISSING], references(request), project,
                              load_conversation_catalog(), recovery=state)
    assert failure.details["outcome"] == "denied"


def test_read_compare_skill_abstains_when_independent_replay_fails(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    for name in ("avant.md", "apres.md"):
        (project / name).touch()
    reads = []

    def incomplete(root, inputs):
        reads.append(root)
        return {"status": "inspected"}

    monkeypatch.setattr(conversation_planning, "inspect_code", incomplete)
    request = "Lis avant.md puis compare avant.md et apres.md"
    failure, = execute_intents(request, [MISSING, MISSING], references(request), project,
                              load_conversation_catalog(), recovery=recovery(tmp_path))
    assert failure.details["outcome"] == "abstain"
    assert len(reads) == 1 and reads[0] != project


def test_unknown_clarification_and_permission_have_separate_outcomes(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    state = recovery(tmp_path)
    missing = execute(state, "Convertis guide.md en PDF", project)
    clarify = execute(state, "Vérifie", project, {"tool": "clarify", "refs": [], "detail": "Quel dossier ?"})
    assert missing.details["outcome"] == "missing" and missing.details["recovery"] == "missing"
    assert clarify.details["outcome"] == "needs_clarification"

    for risk in ("R2", "R3"):
        catalog = load_conversation_catalog()
        catalog["documents.compare"] = {**catalog["documents.compare"], "risk_class": risk}
        denied = execute(state, "Compare avant.md et apres.md", project,
                         {"tool": "documents.compare", "refs": [1, 2], "detail": ""}, catalog)
        assert denied.code == ErrorCode.PERMISSION_DENIED and denied.details["outcome"] == "denied"


def test_recomposition_never_bypasses_path_scope_or_mixed_intent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "avant.md").touch()
    (project / "apres.md").touch()
    (tmp_path / "outside.md").touch()
    state = recovery(tmp_path)
    escape = execute(state, f"Compare « avant.md » et « {tmp_path / 'outside.md'} »", project)
    mixed = execute(state, "Compare avant.md et apres.md, puis publie le résultat.", project)
    assert escape.details["outcome"] == "denied"
    assert mixed.details["outcome"] == "missing"


def test_recurrent_audio_gap_proposes_integration_only_after_single_use_approval(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for name in ("premier.wav", "second.flac"):
        (project / name).touch()
    state = recovery(tmp_path)
    assert execute(state, "Transcris premier.wav", project).details["outcome"] == "missing"
    assert execute(state, "Transcris premier.wav", project).details["outcome"] == "missing"
    pending = execute(state, "Transcris second.flac", project)
    assert pending.details["outcome"] == "awaiting_approval"
    review = GapReview(pending.details["construction_review_id"])
    with pytest.raises(PlanningError, match="Accord requis"):
        state.prepare_integration(review, approved=False)
    result = state.prepare_integration(review, approved=True)
    assert result["outcome"] == "construction_proposed" and result["level"] == "E"
    assert result["contexts"] == (".flac", ".wav") and result["capability"] == "audio.transcribe"
    assert set(result["admissibility"]) == {"A", "B", "C", "D"} and result["cost"]["status"] == "to_measure"
    with pytest.raises(PlanningError, match="plus disponible"):
        state.prepare_integration(review, approved=True)
    with sqlite3.connect(state.database) as db:
        assert not db.execute("SELECT 1 FROM local_capabilities").fetchone()
        report, = db.execute("SELECT report FROM gap_reports WHERE capability = ?", ("audio.transcribe",)).fetchone()
    assert json.loads(report)["events"][-1] == "operator_approved"
    assert "premier.wav" not in report and "second.flac" not in report
