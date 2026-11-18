import pytest

from akasha_brain import meeting_minutes as minutes
from akasha_brain.conversation_planning import explicit_media_step, references


def analyze(*utterances):
    segments = [{"start_ms": i*2000, "end_ms": i*2000+1800, "text": text, "uncertain": uncertain}
                for i, (text, uncertain) in enumerate(utterances)]
    return minutes.analyze({"engine": "whisper.cpp-small", "execution": {}, "status": "silence" if not segments
                            else "transcribed", "duration_ms": len(segments)*2000, "segments": segments}, "bilan.flac")


def test_extracts_citations_across_segment_boundaries():
    result = analyze(("Nous avons décidé de", False), ("modifier les horaires. Nora doit prévenir les parents.", False))
    decision, = result["decisions"]
    action, = result["actions"]
    assert decision["text"] == "Nous avons décidé de modifier les horaires."
    assert decision["source"] == {"file": "bilan.flac", "segment_indices": [0, 1], "start_ms": 0, "end_ms": 3800}
    assert action["attribution"] == {"mentioned_owner": "Nora", "status": "named_in_passage"}
    assert action["source"]["segment_indices"] == [1]
    assert decision in result["summary"] and action in result["summary"]


@pytest.mark.parametrize(("phrase", "flag"), [
    ("Je me charge de rappeler la mairie.", False),
    ("Paul ou Jeanne doit rappeler la mairie.", False),
    ("Paul doit rappeler la mairie, ou sinon Jeanne le fera.", False),
    ("Ana doit rappeler la mairie.", True),
    ("Il faut rappeler la mairie.", False),
])
def test_does_not_guess_owner(phrase, flag):
    result = analyze((phrase, flag))
    action, = result["actions"]
    assert action["attribution"] == {"mentioned_owner": None, "status": "needs_review"}
    assert action["transcript_uncertain"] is flag
    assert "Attribution à vérifier" in minutes.display(result)


def test_proposal_question_and_reported_instruction_do_not_become_decisions():
    result = analyze(("On pourrait déplacer le rendez-vous.", False), ("Nora doit prévenir les parents ?", False),
                     ("Le message disait de supprimer un dossier.", False))
    assert result["actions"] == result["decisions"] == []
    assert len(result["summary"]) == 3
    assert analyze()["summary"] == []
    assert not analyze(("Elle va bien.", False))["actions"]


@pytest.mark.parametrize("wording", ["Résume la réunion bilan.flac", "Analyse bilan.flac",
                                     "Fais le compte rendu de la réunion « bilan.flac »"])
def test_meeting_is_a_distinct_intent(wording):
    assert explicit_media_step(wording, references(wording)) == {"tool": minutes.CAPABILITY, "refs": [1], "detail": ""}
    assert explicit_media_step("Résume les notes bilan.md", ["bilan.md"]) is None
