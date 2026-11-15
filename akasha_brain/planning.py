"""Compiler l'objectif structuré de la baseline Notes."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from contracts.akasha_contracts.validate import validate

CAPABILITIES = Path(__file__).with_name("capabilities.json")
ENVIRONMENT = "bench-notes"
TARGET = "bench://notes"
TEST_PREDICATE = {
    "predicate": "test_suite_passes",
    "on": "CodeState",
    "args": {"command": "pytest -q"},
}
GRAPH = (
    ("localize", "observe", "notes.locate", "1.0.0", ()),
    ("prepare_reference", "edit", "notes.restore_reference", "1.0.0", ("localize",)),
    ("verify", "test", "notes.verify", "1.0.0", ("prepare_reference",)),
)
RBITNET_GRAPH = (
    GRAPH[0],
    ("generate_diff", "edit", "notes.repair_rbitnet", "1.0.0", ("localize",)),
    ("verify", "test", "notes.verify", "1.0.0", ("generate_diff",)),
)


class PlanningError(Exception):
    def __init__(self, error: AkashaError):
        super().__init__(error.message)
        self.error = error


def load_catalog() -> dict[tuple[str, str], dict]:
    entries = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise PlanningError(AkashaError(
            ErrorCode.CONTRACT_SCHEMA_VIOLATION, "Le registre doit contenir une liste de capacités.",
        ))
    catalog = {}
    for entry in entries:
        manifest = entry.get("manifest") if isinstance(entry, dict) else None
        problems = validate(manifest, "CapabilityManifest")
        if problems:
            raise PlanningError(problems[0])
        key = (manifest["capability_id"], manifest["version"])
        if "evaluation" in entry:
            evaluation = entry["evaluation"]
            if not isinstance(evaluation, dict) or not all(
                isinstance(evaluation.get(field), str) and evaluation[field].strip()
                for field in ("environment_id", "evidence")
            ):
                raise PlanningError(AkashaError(
                    ErrorCode.CONTRACT_SCHEMA_VIOLATION, "Relevé d'évaluation invalide.",
                    {"capability_id": key[0], "version": key[1]},
                ))
        if key in catalog:
            raise PlanningError(AkashaError(
                ErrorCode.CONTRACT_SCHEMA_VIOLATION, "Capacité en double dans le registre.",
                {"capability_id": key[0], "version": key[1]},
            ))
        catalog[key] = entry
    return catalog


def compile_goal(goal: dict, catalog: dict[tuple[str, str], dict], *, rbitnet: bool = False) -> dict:
    problems = validate(goal, "GoalSpec")
    if problems:
        raise PlanningError(problems[0])
    constraints = goal.get("constraints", {})
    if goal.get("inputs") != [TARGET] or constraints.get("environment_id") != ENVIRONMENT:
        raise PlanningError(AkashaError(
            ErrorCode.CAPABILITY_UNAVAILABLE, "Aucun parcours évalué pour cette cible.",
        ))
    if goal.get("uncertainties"):
        raise PlanningError(AkashaError(
            ErrorCode.NEEDS_CLARIFICATION, "L'objectif comporte des incertitudes à résoudre.",
        ))
    if goal.get("approval_requirements"):
        raise PlanningError(AkashaError(
            ErrorCode.APPROVAL_REQUIRED, "L'objectif comporte une approbation à obtenir.",
        ))
    graph = RBITNET_GRAPH if rbitnet else GRAPH
    required_actions = {action for _, action, *_ in graph}
    if goal["risk_class"] != "R1" or not required_actions.issubset(constraints.get("allowed_actions", [])):
        raise PlanningError(AkashaError(
            ErrorCode.PERMISSION_DENIED, "Le parcours exige la classe R1 et les trois actions déclarées.",
            {"required_actions": sorted(required_actions)},
        ))
    if set(constraints) - {"allowed_actions", "environment_id"} or goal.get("resource_budget"):
        raise PlanningError(AkashaError(
            ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le parcours ne sait pas traiter ces contraintes ou ce budget.",
        ))
    if goal["success_conditions"] not in ([TEST_PREDICATE], [{"all_of": [TEST_PREDICATE]}]):
        raise PlanningError(AkashaError(
            ErrorCode.CAPABILITY_UNAVAILABLE, "Aucun vérificateur évalué pour ces conditions de réussite.",
        ))

    steps = []
    for step_id, action, capability_id, version, dependencies in graph:
        entry = catalog.get((capability_id, version))
        evaluation = entry.get("evaluation", {}) if entry else {}
        if evaluation.get("environment_id") != ENVIRONMENT or not evaluation.get("evidence"):
            raise PlanningError(AkashaError(
                ErrorCode.CAPABILITY_UNAVAILABLE, "Capacité évaluée indisponible pour le banc Notes.",
                {"capability_id": capability_id, "version": version},
            ))
        manifest = entry["manifest"]
        sandbox = manifest.get("sandbox", {})
        if (sandbox.get("tier") != "windows-sandbox" or sandbox.get("network_egress") is not False
                or manifest["risk_class"] != goal["risk_class"]
                or manifest["permissions"].get("network")
                or manifest.get("side_effects") != "local-temporary"):
            raise PlanningError(AkashaError(
                ErrorCode.PERMISSION_DENIED, "Manifeste incompatible avec le banc confiné.",
                {"capability_id": capability_id, "version": version},
            ))
        steps.append({
            "id": step_id, "action": action, "capability_id": capability_id,
            "version": version, "depends_on": list(dependencies), "evidence": evaluation["evidence"],
        })
    return {
        "goal_id": goal["goal_id"],
        "graph_id": "notes-rbitnet" if rbitnet else "notes-baseline",
        "graph_version": "1.0.0",
        "environment_id": ENVIRONMENT,
        "sandbox_tier": "windows-sandbox",
        "steps": steps,
        "expected_validation": {"tests_passed": 4, "verifier": "sqlite_persistence"},
    }
