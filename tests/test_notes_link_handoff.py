from hashlib import sha256

import pytest

from akasha_brain.notes_link_candidate import ADAPTER_STEP, INPUT_NAME, PATCH_CHECKS
from bench.run_guided_repair import CHECKPOINTS
from bench.run_notes_link_handoff import CASES, measure, observe_validity, perturb


@pytest.mark.parametrize("case", CASES)
def test_reserved_handoff_oracle_distinguishes_the_control(tmp_path, case):
    prepared = tmp_path / INPUT_NAME
    prepared.mkdir()
    staged = prepared / "proposal.diff"
    staged.write_bytes(b"prepared patch")
    digest = sha256(staged.read_bytes()).hexdigest()
    receipt = {**PATCH_CHECKS, "guest_apply_exit": 0x4602, "matches_desktop_protocol": True,
               "diff_file": f"{INPUT_NAME}/proposal.diff", "diff_sha256": digest}
    observed = perturb(case, receipt, staged, digest)
    assert observe_validity(observed) is (case == "valid_control")
    assert observed["applied_digest"] == digest


def test_unexpected_candidate_dispatch_still_counts_as_a_false_acceptance():
    graph = {"steps": [{"id": ADAPTER_STEP}]}
    report = {"graph": graph, "trace": [], "status": "passed", "sandbox_id": "fresh", "sandbox_stopped": True,
              "wall_s": 10, "repair": {"backend": "cpu", "hashes": CHECKPOINTS, "seeds": (742,)}}
    handoff = {"received_digest": None, "applied_digest": "content", "staged_digest": "content",
               "received_path": f"{INPUT_NAME}/proposal.diff"}
    result = measure(report, {"handoff": handoff, "verify_calls": 1}, graph,
                     {"id": "missing_digest", "seed": 742, "valid": False})
    assert result["evaluated"] is True
    assert result["expected_behavior"] is False
    assert result["false_handoff_acceptances"] == 1
