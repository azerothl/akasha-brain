from akasha_brain.link_diagnostics import diagnose_links


GRAPH = {"steps": [
    {"id": "localize", "depends_on": []},
    {"id": "generate_diff", "depends_on": ["localize"]},
    {"id": "verify", "depends_on": ["generate_diff"]},
]}
LOCALIZED = {"id": "localize", "status": "passed", "result": {"tests": 4, "failures": 2, "pytest_exit": 1}}
PATCH = {"diff_applied": True, "git_apply_check": True, "guest_sha256_verified": True}


def outcomes(graph, trace):
    return {(row["source"], row["target"], row["attempt"]): row
            for row in diagnose_links(graph, trace)}


def test_diagnostics_distinguish_failed_producer_and_failed_consumer_on_retries():
    trace = [LOCALIZED, {"id": "generate_diff", "attempt": 1, "status": "failed"},
             {"id": "generate_diff", "attempt": 2, "status": "passed", "result": PATCH},
             {"id": "verify", "attempt": 2, "status": "failed", "authorization": "allowed"}]
    result = outcomes(GRAPH, trace)
    assert result["localize", "generate_diff", 1]["status"] == "consumer_failed"
    assert result["localize", "generate_diff", 2]["status"] == "verified"
    assert result["generate_diff", "verify", 1]["status"] == "producer_failed"
    assert result["generate_diff", "verify", 2]["status"] == "consumer_failed"


def test_diagnostics_require_typed_evidence_and_distinguish_permission_refusal():
    proposal = {"id": "generate_diff", "status": "passed",
                "result": {"diff_applied": 1, "git_apply_check": True, "raw_diff": "sensitive payload"}}
    verification = {"id": "verify", "status": "failed", "authorization": "denied"}
    result = outcomes(GRAPH, [LOCALIZED, proposal, verification])["generate_diff", "verify", 1]
    assert result == {"source": "generate_diff", "target": "verify", "attempt": 1, "status": "handoff_invalid",
                      "missing_checks": ["guest_sha256_verified"], "invalid_checks": ["diff_applied"]}
    proposal["result"] = PATCH
    result = outcomes(GRAPH, [LOCALIZED, proposal, verification])
    assert result["generate_diff", "verify", 1]["status"] == "consumer_permission_denied"
    reordered = outcomes(GRAPH, [LOCALIZED, verification, proposal])
    assert reordered["generate_diff", "verify", 1]["status"] == "producer_out_of_order"
