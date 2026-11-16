"""Diagnostique les remises entre les étapes du graphe synthétique Notes."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from .notes_link_candidate import ADAPTER_STEP, INPUT_NAME, PATCH_CHECKS
from .planning import ENVIRONMENT


NOTES_HANDOFFS = {
    ("localize", "generate_diff"): {"tests": 4, "failures": 2, "pytest_exit": 1},
    ("localize", "prepare_reference"): {"tests": 4, "failures": 2, "pytest_exit": 1},
    ("generate_diff", "verify"): PATCH_CHECKS,
    ("generate_diff", ADAPTER_STEP): PATCH_CHECKS,
    (ADAPTER_STEP, "verify"): {"input_name": INPUT_NAME},
    ("prepare_reference", "verify"): {"reference_sha256_verified_in_guest": True},
    ("verify", "verify_desktop"): {"passed": 4, "pytest_exit": 0, "sqlite_verifier_exit": 0},
}


def diagnose_handoff(source, target, checks: dict | None) -> dict:
    if checks is None:
        return {"status": "contract_not_declared"}
    if source is None:
        return {"status": "producer_not_observed"}
    source_position, producer = source
    if target is not None and source_position >= target[0]:
        return {"status": "producer_out_of_order"}
    if producer["status"] == "running":
        return {"status": "producer_in_progress"}
    if producer["status"] != "passed":
        return {"status": "producer_failed"}
    result = producer.get("result", {})
    if not isinstance(result, dict):
        return {"status": "handoff_invalid", "missing_checks": list(checks), "invalid_checks": []}
    missing = [name for name in checks if name not in result]
    invalid = [name for name, expected in checks.items()
               if name in result and (type(result[name]) is not type(expected) or result[name] != expected)]
    if missing or invalid:
        return {"status": "handoff_invalid", "missing_checks": missing, "invalid_checks": invalid}
    if target is None:
        return {"status": "consumer_not_observed"}
    _, consumer = target
    if consumer.get("authorization") == "denied":
        return {"status": "consumer_permission_denied"}
    if consumer["status"] == "running":
        return {"status": "consumer_in_progress"}
    return {"status": "verified" if consumer["status"] == "passed" else "consumer_failed"}


def diagnose_links(graph: dict, trace: list[dict]) -> list[dict]:
    """Garde les tentatives indépendantes et réutilise l'observation initiale."""
    indexed = defaultdict(dict)
    for position, row in enumerate(trace):
        indexed[row["id"]][row.get("attempt", 1)] = (position, row)
    diagnostics = []
    for target in graph["steps"]:
        target_id = target["id"]
        consumers = indexed[target_id]
        for source_id in target["depends_on"]:
            producers = indexed[source_id]
            attempts = consumers.keys() if source_id == "localize" else producers.keys() | consumers.keys()
            for attempt in sorted(attempts or {1}):
                source_attempt = 1 if source_id == "localize" else attempt
                result = diagnose_handoff(producers.get(source_attempt), consumers.get(attempt),
                                          NOTES_HANDOFFS.get((source_id, target_id)))
                diagnostics.append({"source": source_id, "target": target_id, "attempt": attempt, **result})
    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_bytes())
    if report["graph"].get("environment_id") != ENVIRONMENT:
        parser.error("Le rapport doit provenir du banc Notes.")
    print(json.dumps(diagnose_links(report["graph"], report["trace"]), indent=2))


if __name__ == "__main__":
    main()
