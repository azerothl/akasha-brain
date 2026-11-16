"""Conversion candidate du reçu Git en entrée typée du vérificateur Notes."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from bench.run_guided_repair import file_hash
from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from contracts.akasha_contracts.validate import validate

from .planning import PlanningError

ADAPTER_STEP = "adapt_patch_receipt"
PATCH_CHECKS = {"diff_applied": True, "git_apply_check": True, "guest_sha256_verified": True}
INPUT_NAME = "rbitnet-1"
ADAPTER = {
    "capability_id": "notes.adapt_patch_receipt",
    "version": "1.0.0",
    "kind": "adapter",
    "input_schema": {
        "type": "object",
        "required": [*PATCH_CHECKS, "diff_file", "diff_sha256", "guest_apply_exit", "matches_desktop_protocol"],
        "properties": {
            **{field: {"const": expected} for field, expected in PATCH_CHECKS.items()},
            "diff_file": {"const": f"{INPUT_NAME}/proposal.diff"},
            "diff_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "guest_apply_exit": {"const": 0x4602},
            "matches_desktop_protocol": {"const": True},
        },
    },
    "output_schema": {
        "type": "object",
        "required": ["input_name", "diff_sha256"],
        "properties": {
            "input_name": {"const": INPUT_NAME},
            "diff_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        },
        "additionalProperties": False,
    },
    "preconditions": ["guest_git_apply_verified", "frozen_notes_desktop_protocol"],
    "postconditions": ["checked_diff_digest", "authorized_guest_input"],
    "permissions": {"reads": [f"staging:{INPUT_NAME}/proposal.diff"], "writes": [], "execute": [], "network": []},
    "risk_class": "R1",
    "sandbox": {"tier": "windows-sandbox", "network_egress": False},
    "side_effects": "none",
}


@dataclass(frozen=True)
class VerifiedPatch:
    input_name: str
    diff_sha256: str


def compile_candidate(parent: dict) -> dict:
    if (parent["graph_id"], parent["graph_version"]) != ("notes-rbitnet-ocr", "1.0.0"):
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED,
                                        "L'adaptateur exige le graphe parent Notes avec RapidOCR."))
    if errors := validate(ADAPTER, "CapabilityManifest"):
        raise PlanningError(errors[0])
    candidate = deepcopy(parent)
    localize, generate, verify, desktop = candidate["steps"]
    verify["depends_on"] = [ADAPTER_STEP]
    candidate["steps"] = [localize, generate, {
        "id": ADAPTER_STEP,
        "action": "observe",
        "capability_id": ADAPTER["capability_id"],
        "version": ADAPTER["version"],
        "depends_on": [generate["id"]],
    }, verify, desktop]
    candidate.update(graph_id="notes-rbitnet-ocr-typed-patch", graph_version="1.1.0",
                     parent={key: parent[key] for key in ("graph_id", "graph_version")}, adapter=deepcopy(ADAPTER))
    return candidate


def adapt_patch_receipt(receipt: dict, stage: Path, expected_digest: str) -> VerifiedPatch:
    expected = {
        **PATCH_CHECKS, "diff_file": f"{INPUT_NAME}/proposal.diff", "diff_sha256": expected_digest,
        "guest_apply_exit": 0x4602, "matches_desktop_protocol": True,
    }
    invalid = [key for key, value in expected.items()
               if type(receipt.get(key)) is not type(value) or receipt[key] != value]
    if invalid:
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Reçu Git incompatible.",
                                        {"invalid_checks": invalid}))
    path = stage.resolve() / INPUT_NAME / "proposal.diff"
    if path.resolve() != path or not path.is_file() or file_hash(path) != expected_digest:
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED,
                                        "Le diff préparé ne correspond plus au reçu Git.",
                                        {"invalid_checks": ["staged_diff_sha256"]}))
    return VerifiedPatch(INPUT_NAME, expected_digest)
