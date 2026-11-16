from copy import deepcopy
from hashlib import sha256
import json

import pytest

from akasha_brain.notes_evolution import GOAL_FILE
from akasha_brain.notes_link_candidate import PATCH_CHECKS, VerifiedPatch, adapt_patch_receipt, compile_candidate
from akasha_brain.planning import PlanningError, compile_goal, load_catalog
from bench.run_notes_link_comparison import ROOT, compile_graphs, require_freeze


def test_candidate_compilation_keeps_an_independent_parent():
    parent = compile_goal(json.loads(GOAL_FILE.read_bytes()), load_catalog(), rbitnet=True, rapidocr=True)
    saved = deepcopy(parent)
    candidate = compile_candidate(parent)
    assert candidate["parent"]["graph_id"] == parent["graph_id"]
    assert candidate["steps"][2]["depends_on"] == ["generate_diff"]
    assert candidate["steps"][3]["depends_on"] == ["adapt_patch_receipt"]
    assert candidate["expected_validation"] == parent["expected_validation"]
    candidate["expected_validation"]["tests_passed"] = 0
    assert parent == saved


def test_adapter_rejects_a_mismatched_receipt_and_a_tampered_staged_diff(tmp_path):
    patch = b"test fixture patch"
    digest = sha256(patch).hexdigest()
    staged = tmp_path / "rbitnet-1"
    staged.mkdir()
    diff = staged / "proposal.diff"
    diff.write_bytes(patch)
    receipt = {**PATCH_CHECKS, "diff_file": "rbitnet-1/proposal.diff", "diff_sha256": digest,
               "guest_apply_exit": 0x4602, "matches_desktop_protocol": True}
    assert adapt_patch_receipt(receipt, tmp_path, digest) == VerifiedPatch("rbitnet-1", digest)
    with pytest.raises(PlanningError) as refusal:
        adapt_patch_receipt({**receipt, "diff_file": "rbitnet-2/proposal.diff", "diff_applied": 1}, tmp_path, digest)
    assert refusal.value.error.details["invalid_checks"] == ["diff_applied", "diff_file"]
    diff.write_bytes(b"modified patch")
    with pytest.raises(PlanningError) as refusal:
        adapt_patch_receipt(receipt, tmp_path, digest)
    assert refusal.value.error.details["invalid_checks"] == ["staged_diff_sha256"]


def test_notes_link_freeze_pins_three_distinct_seeds_and_alternating_order():
    lock = ROOT / "akasha_brain" / "protocols" / "notes-link-adapter-v1.json"
    frozen = json.loads(lock.read_bytes())
    graphs = compile_graphs()[2]
    require_freeze(frozen, graphs)
    schedule = frozen["schedule"]
    assert [row["seed"] for row in schedule] == [742, 743, 744]
    assert [row["order"] for row in schedule] == [
        ["parent", "candidate"], ["candidate", "parent"], ["parent", "candidate"],
    ]
    schedule[1]["order"].reverse()
    with pytest.raises(RuntimeError, match="a dérivé"):
        require_freeze(frozen, graphs)
