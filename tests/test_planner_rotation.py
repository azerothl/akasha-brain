from PIL import Image

from akasha_brain.conversation_planning import execute_intents, load_conversation_catalog, references
from bench.run_planner_rotation_ambiguity import ask, verify
from contracts.akasha_contracts.errors import ErrorCode


def test_ambiguity_replay(tmp_path):
    assert verify(tmp_path)["summary"] == {
        "corners": {"abstain": 64, "verified_png": 0},
        "visual": {"abstain": 32, "verified_png": 32},
    }


def test_rectangular_rotation_and_conflicting_reference(tmp_path):
    source = Image.frombytes("L", (4, 3), bytes(range(12)))
    source.save(tmp_path / "source.png")
    target = source.transpose(Image.Transpose.ROTATE_270)
    target.save(tmp_path / "ref.png")
    catalog = load_conversation_catalog()
    request = "Oriente source.png comme ref.png"
    assert ask(tmp_path, request, catalog).output.proof["clockwise_degrees"] == 90
    target.putpixel((1, 1), 80)
    target.save(tmp_path / "ref.png")
    error = ask(tmp_path, request, catalog)
    assert error.details["outcome"] == "abstain" and error.details["matching_rotations"] == []
    assert error.details["corner_candidates"] == [90]
    assert ask(tmp_path, "Oriente source.png", catalog).details["outcome"] == "abstain"


def test_orientation_checks_project_and_requested_evidence(tmp_path):
    folder = tmp_path / "selected"
    folder.mkdir()
    Image.new("L", (2, 2)).save(folder / "source.png")
    catalog = load_conversation_catalog()
    assert ask(folder, "Oriente source.png comme ../ref.png", catalog).code == ErrorCode.PERMISSION_DENIED
    request = "Oriente source.png comme ref.png selon les coins uniquement"
    step = {"tool": "image.orient", "refs": [1, 2], "detail": "visual"}
    result, = execute_intents(request, step, references(request), folder, catalog)
    assert result.code == ErrorCode.NEEDS_CLARIFICATION
