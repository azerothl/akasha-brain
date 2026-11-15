import json

import pytest

from akasha_brain import notes_repair
from bench.run_guided_repair import propose_change


SOURCE = """class NoteStore:
    def save_note(self, title: str) -> int:
        return 0

    def keep(self):
        return 7
"""


def test_generated_diff_and_candidate_preserve_the_other_methods():
    diff, candidate = propose_change(SOURCE, "def save_note(self, title: str) -> int:\n    return 1")
    assert diff.startswith("--- a/notes_store.py\n+++ b/notes_store.py\n")
    assert "\n-        return 0\n+        return 1\n" in diff
    assert candidate == SOURCE.replace("return 0", "return 1")


@pytest.mark.parametrize("proposal", [
    "def save_note(self, other: str) -> int:\n    return 1",
    "def save_note(self, title: str) -> int:\n    return 1\n\ndef other():\n    pass",
])
def test_rejects_signature_changes_and_edits_outside_the_method(proposal):
    with pytest.raises(ValueError):
        propose_change(SOURCE, proposal)


def test_frozen_prompt_rejects_text_with_a_stale_digest(tmp_path, monkeypatch):
    changed = json.loads(notes_repair.PROMPT_FILE.read_text(encoding="utf-8"))
    changed["requirements"] += "\nChange."
    fixture = tmp_path / "prompt.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(notes_repair, "PROMPT_FILE", fixture)
    with pytest.raises(RuntimeError, match="empreinte"):
        notes_repair.load_repair_prompt()
