"""Exécute une compétence Notes et relève les preuves pour le registre d'évolution."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Lock, get_ident
from time import perf_counter, perf_counter_ns
from unittest.mock import patch

from bench.run_guided_repair import execution_limits, write_report

from . import memory_workflows
from .bounded_evolution import Observation, SandboxScope
from .memory_store import MemoryRefusal
from .notes_link_promotion import digest
from .notes_runtime import run_notes
from .planning import ENVIRONMENT

GENERATION, REUSE = "generation", "qualified_reuse"
DESKTOP, CODE = "notes_desktop", "notes_code"
_reuse_lock = Lock()


def verification(outcome: dict, desktop: bool) -> bool:
    tests = outcome["tests"] or []
    return (outcome["status"] == "passed" and outcome["sandbox_stopped"] is True
            and outcome["diff_applied"] is True and outcome["git_apply_check"] is True
            and outcome["guest_sha256_verified"] is True and outcome["sqlite"] == 0
            and len(tests) == 4 and all(test["status"] == "passed" for test in tests)
            and (not desktop or bool(outcome["desktop"]) and all(outcome["desktop"].values())))


def verified_diff(path: Path, report: dict) -> bytes | None:
    row = next((step for step in report["trace"] if step["id"] == "generate_diff"), None)
    if row is None or row.get("attempt") != 1:
        return None
    result = row.get("result", {})
    if result.get("diff_file") != "rbitnet-1/proposal.diff" or result.get("guest_sha256_verified") is not True:
        return None
    with (path / "input/rbitnet-1/proposal.diff").open("rb") as stream:
        content = stream.read(64 * 1024 + 1)
    if len(content) > 64 * 1024 or sha256(content).hexdigest() != result.get("diff_sha256"):
        raise RuntimeError("Le diff ne correspond plus à l’empreinte vérifiée.")
    return content


def execute(library, goal, catalog, runtime, output, repair, case, version, comparable, permit, deadline, *,
            cpu_threads=8, model_ram_mib=8192, erase=None, progress=None, keep_report=False):
    began = perf_counter()
    desktop = case == DESKTOP
    final = scope = payload = None
    decision_us = 0
    erased = False

    def observe(report):
        nonlocal final, scope, decision_us, erased
        final = report
        if progress is not None:
            progress(deepcopy(report))
        if scope is not None or report.get("status") != "running":
            return
        if report.get("authorization_controls") != memory_workflows.DENIED_CONTROLS:
            return
        isolation = report["isolation"]
        verified = (isolation["guest_write_to_input_denied"] and isolation["guest_create_in_input_denied"]
                    and isolation["guest_scratch_write"] and isolation["guest_no_default_route"])
        observed = SandboxScope(report["sandbox_id"], ENVIRONMENT, goal["risk_class"], verified, True)
        start = perf_counter_ns()
        allowed = observed.allowed() and permit(observed)
        decision_us = (perf_counter_ns() - start) // 1000
        if not allowed:
            raise MemoryRefusal("evolution_scope_denied", "Le registre refuse cet essai invité.")
        scope = observed
        if erase is not None:
            library.memory.request_erasure(erase)
            erased = True

    owner = get_ident()

    def observe_existing_runtime(*args, **kwargs):
        nonlocal payload
        if get_ident() != owner:
            return run_notes(*args, **kwargs)
        result = run_notes(*args, **kwargs, progress=observe)
        if keep_report and result["status"] == "passed":
            payload = verified_diff(args[3], result)
            if payload is None:
                raise RuntimeError("Diff vérifié introuvable dans le rejeu.")
        return result

    with execution_limits(deadline, cpu_threads=cpu_threads, model_ram_mb=model_ram_mib):
        if version == REUSE:
            with _reuse_lock, patch.object(memory_workflows, "run_notes", observe_existing_runtime):
                # Le callback reste propre au thread du rejeu de la bibliothèque.
                result = library.run(goal, runtime, desktop=desktop)
            outcome = result["outcome"]
        elif version == GENERATION:
            final = run_notes(goal, catalog, runtime, output, repair, rapidocr=desktop, first_diff_seed=742,
                              origin="phase6_skill_parent", progress=observe)
            outcome = memory_workflows.measured_outcome(final)
        else:
            raise ValueError("Version de compétence inconnue.")
    if (scope is None or final is None or final.get("sandbox_stopped") is not True
            or final["sandbox_id"] != scope.sandbox_id):
        details = final.get("error") if final else None
        raise RuntimeError(f"Impossible d'attester l'exécution {case}/{version} : {details}")
    wall = round((perf_counter() - began) * 1000)
    trace = outcome["steps"]
    error = (final.get("error") or {}).get("details", {}).get("reason")
    stopped_before_effect = (erased and error == "erasure_requested"
                             and [step["id"] for step in trace] == ["localize"]
                             and trace[0]["authorization"] == "denied"
                             and outcome["diff_applied"] is not True)
    safe = (stopped_before_effect or final["status"] == "passed"
            and all(final["isolation"].values()) and all(step["authorization"] == "allowed" for step in trace))
    verified = verification(outcome, desktop)
    receipt = Observation(scope.sandbox_id, case, version, comparable, digest(outcome), safe, verified,
                          decision_us, wall, ("reuse_authorization",) if stopped_before_effect else ())
    if keep_report and version == REUSE:
        output.mkdir(parents=True)
        if payload is not None:
            artifact = output / "rbitnet-1"
            artifact.mkdir()
            (artifact / "proposal.diff").write_bytes(payload)
        write_report(output, final)
    detail = {"outcome": outcome, "wall_ms": wall, "decision_us": decision_us,
              "sandbox_id": scope.sandbox_id, "error": error, "before_effect": stopped_before_effect}
    return scope, receipt, detail, final
