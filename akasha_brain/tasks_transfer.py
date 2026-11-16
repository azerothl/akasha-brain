"""Parcours de réparation Rbitnet du banc Tâches réservé au transfert."""

import ast
from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
import secrets
import shutil
import subprocess
from time import perf_counter
from uuid import UUID, uuid4

from bench.run_guided_repair import (
    BENCH, CHECKPOINTS, HTTP_TIMEOUT_S, execution_limits, file_hash, first_code_block, infer, write_report, wsb,
)
from bench.harness.tasks_oracle_deltas import COUNT_LIMIT, decode_oracle
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .notes_repair import RbitnetPaths, stage_git
from .notes_sandbox import (
    CHANNELS, POWERSHELL, active_sandboxes, guest_exit, read_profile, require_step_permission, wait_for_guest,
)
from .planning import PlanningError, TASKS_ENVIRONMENT, TASKS_MAX_ATTEMPTS, compile_goal, load_catalog

ROOT = BENCH.parent
PROMPT = Path("akasha_brain/prompts/python-repair-v1.txt")
GUEST_FILES = (
    "run_tasks_validation.ps1", "probe_notes_isolation.ps1", "probe_guest_channels.ps1", "tasks_oracle_deltas.py",
)
FROZEN_FILES = (
    Path("akasha_brain/__main__.py"), Path("akasha_brain/capabilities.json"),
    Path("akasha_brain/planning.py"), Path("akasha_brain/tasks_transfer.py"),
    Path("akasha_brain/notes_repair.py"), Path("akasha_brain/notes_sandbox.py"),
    Path("bench/run_guided_repair.py"), PROMPT,
    Path("contracts/examples/goal_tasks_repair.json"),
    *(Path("bench/harness") / name for name in (*GUEST_FILES, "akasha-bench.wsb")),
)
MAX_TOKENS = 384
SEED = 742
RBITNET_CONFIGURATION = {
    "hashes": CHECKPOINTS, "backend": "cpu", "seed": SEED, "max_tokens": MAX_TOKENS,
    "cpu_threads": 8, "model_ram_mib": 8192, "http_timeout_s_by_attempt": [HTTP_TIMEOUT_S, 300],
}


@dataclass(frozen=True)
class Proposal:
    diff: str
    file_sha256: str
    ast_sha256: str


def plan_identity(plan: dict) -> dict:
    return {key: value for key, value in plan.items() if key != "goal_id"}


def frozen_inputs() -> dict:
    files = [
        *FROZEN_FILES,
        *(path.relative_to(ROOT) for path in sorted((ROOT / "contracts/schemas").rglob("*.json"))),
        *(path.relative_to(ROOT) for path in sorted((ROOT / "contracts/akasha_contracts").glob("*.py"))),
    ]
    return {
        path.as_posix(): sha256((ROOT / path).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        for path in sorted(files)
    }


def freeze_transfer(destination: Path) -> dict:
    nominal = json.loads((ROOT / "contracts/examples/goal_tasks_repair.json").read_text(encoding="utf-8"))
    plan = compile_goal(nominal, load_catalog(), rbitnet=True)
    frozen = {
        "plan": plan_identity(plan),
        "inputs": frozen_inputs(),
        "rbitnet": RBITNET_CONFIGURATION,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(frozen, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return frozen


def replace_definition(source: str, response: str) -> Proposal:
    replacement = first_code_block(response)
    proposed = ast.parse(replacement).body
    if len(proposed) != 1 or not isinstance(proposed[0], ast.FunctionDef) or proposed[0].decorator_list:
        raise ValueError("La réponse doit fournir une seule définition de fonction ordinaire.")
    candidate = proposed[0]
    nodes = ast.parse(source).body
    definitions = [*nodes, *(member for node in nodes if isinstance(node, ast.ClassDef) for member in node.body)]
    targets = [node for node in definitions if isinstance(node, ast.FunctionDef) and node.name == candidate.name]
    if len(targets) != 1 or targets[0].decorator_list:
        raise ValueError("La définition cible est absente, ambiguë ou décorée.")
    target = targets[0]
    annotations = [ast.dump(node.returns) if node.returns is not None else None for node in (target, candidate)]
    if (ast.dump(target.args) != ast.dump(candidate.args) or annotations[0] != annotations[1]
            or target.type_params or candidate.type_params):
        raise ValueError("La signature d'origine doit être conservée.")
    lines = source.splitlines(keepends=True)
    indent = lines[target.lineno - 1][:target.col_offset]
    new_lines = [(indent + line) if line.strip() else line for line in (replacement + "\n").splitlines(keepends=True)]
    updated = lines[:target.lineno - 1] + new_lines + lines[target.end_lineno:]
    updated_source = "".join(updated)
    tree = ast.parse(updated_source)
    diff = "".join(unified_diff(lines, updated, fromfile="a/repair.py", tofile="b/repair.py"))
    if not diff:
        raise ValueError("La proposition ne modifie pas le module.")
    return Proposal(
        diff,
        sha256(updated_source.encode("utf-8")).hexdigest(),
        sha256(ast.dump(tree).encode("utf-8")).hexdigest(),
    )


def distinct_proposal(proposal: Proposal, previous: Proposal) -> bool:
    return proposal.diff != previous.diff and proposal.ast_sha256 != previous.ast_sha256


def verification_feedback(checks: dict) -> str:
    def count(value: int) -> str:
        return f"at least {COUNT_LIMIT}" if value == COUNT_LIMIT else str(value)

    lines = []
    for name, passed in checks["filters"].items():
        delta = checks["filter_deltas"][name]
        order = "not measured" if delta["missing"] or delta["unexpected"] else ("yes" if delta["wrong_order"] else "no")
        lines.append(
            f"{name}: {'PASS' if passed else 'FAIL'}. Missing rows: {count(delta['missing'])}. "
            f"Unexpected rows: {count(delta['unexpected'])}. Order mismatch: {order}."
        )
    lines.append(f"SQLite state preserved: {'PASS' if checks['sqlite_unchanged'] else 'FAIL'}")
    return "\n".join(lines)


def baseline_filter_regressions(initial: dict, checks: dict) -> list[str]:
    return [name for name, passed in initial["filters"].items() if passed and not checks["filters"][name]]


def failed_filters(checks: dict) -> list[str]:
    return [name for name, passed in checks["filters"].items() if not passed]


def repair_prompt(intent: str, source: str, initial: dict, *, sqlite_schema: str,
                  previous_checks: dict | None = None) -> str:
    baseline = "\n".join(f"{name}: {'PASS' if passed else 'FAIL'}" for name, passed in initial["filters"].items())
    prompt = (f"{(ROOT / PROMPT).read_text(encoding='utf-8')}\nTask: {intent}\n"
              f"Observed checks:\n{baseline}\n\n")
    targets = failed_filters(initial if previous_checks is None else previous_checks)
    if previous_checks is not None:
        protected = [name for name, passed in initial["filters"].items() if passed]
        regressed = baseline_filter_regressions(initial, previous_checks)
        prompt += f"Independent verification after the first attempt:\n{verification_feedback(previous_checks)}\n"
        if protected:
            prompt += f"Mandatory: these filters passed on the original module and must still pass: {', '.join(protected)}.\n"
        if regressed:
            prompt += f"Restore the original behavior of these filters broken by the previous proposal: {', '.join(regressed)}.\n"
        prompt += (
            "Use the feedback to fix the remaining failures and preserve all passing checks. "
            "Write the replacement for a fresh copy of the original module below.\n\n"
        )
    if targets:
        prompt += (
            f"Required target filters: {', '.join(targets)}. "
            "Change the executable logic that selects or orders the rows for each target filter. "
            "The replacement must make each targeted filter pass the independent check.\n\n"
        )
    return f"{prompt}SQLite schema (DDL):\n```sql\n{sqlite_schema}\n```\n\nPython module:\n{source}"


def evaluate_proposals(run_attempt, initial: dict) -> int | None:
    previous = None
    for attempt in range(1, TASKS_MAX_ATTEMPTS + 1):
        proposal, checks = run_attempt(attempt, previous)
        if previous is not None and baseline_filter_regressions(initial, checks):
            return None
        if all(checks["filters"].values()) and checks["sqlite_unchanged"]:
            return attempt
        previous = (proposal, checks)
    return None


def run_tasks_transfer(goal: dict, catalog: dict, runtime: Path, output: Path, repair: RbitnetPaths,
                       case: Path, lock: Path) -> dict:
    plan = compile_goal(goal, catalog, rbitnet=True)
    if plan["environment_id"] != TASKS_ENVIRONMENT:
        raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Objectif Tâches requis."))
    output.mkdir(parents=True)
    wall = perf_counter()
    report = {"graph": plan, "status": "running", "evolution": "excluded", "trace": []}
    sandbox = None
    try:
        frozen = json.loads(lock.read_text(encoding="utf-8"))
        if plan_identity(plan) != frozen["plan"] or frozen_inputs() != frozen["inputs"]:
            raise RuntimeError("Le graphe ou ses entrées diffèrent du gel.")
        report["freeze_sha256"] = file_hash(lock)
        if active_sandboxes():
            raise RuntimeError("Une session Windows Sandbox est déjà active.")
        if json.loads((case / "goal.json").read_text(encoding="utf-8")) != goal:
            raise RuntimeError("L'objectif diffère de celui de la variante réservée.")
        configuration = frozen["rbitnet"]
        if configuration != RBITNET_CONFIGURATION or repair.verify() != configuration["hashes"]:
            raise RuntimeError("Les paramètres Rbitnet diffèrent du gel.")
        report["rbitnet"] = configuration
        profile = read_profile()
        stage = output / "input"
        stage.mkdir()
        shutil.copytree(case, stage / "case", ignore=shutil.ignore_patterns("__pycache__"))
        staged_case = stage / "case"
        schema_file = plan["repair_context"]["sqlite_schema"]
        sqlite_schema = (staged_case / schema_file).read_text(encoding="utf-8").strip()
        if not sqlite_schema:
            raise ValueError("Le schéma SQLite de la variante est vide.")
        staged_module = staged_case / "repair.py"
        source = staged_module.read_text(encoding="utf-8")
        staged_module.write_bytes(source.encode("utf-8"))
        fixture_hashes = {path.relative_to(staged_case).as_posix(): file_hash(path)
                          for path in staged_case.rglob("*") if path.is_file()}
        report["case_sha256"] = fixture_hashes
        shutil.copytree(runtime, stage / "python")
        report["git"] = stage_git(stage)
        for name in GUEST_FILES:
            shutil.copyfile(BENCH / "harness" / name, stage / name)
        tag = secrets.token_hex(4)
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        entry = fr"C:\AkashaGuidedInput-{tag}"
        sandbox = str(uuid4())
        report["sandbox_id"] = sandbox
        if str(UUID(wsb("start", "--id", sandbox, "--config", profile)["Id"])) != sandbox:
            raise RuntimeError("Identifiant du bac inattendu.")
        wait_for_guest(sandbox)
        wsb("share", "--id", sandbox, "--host-path", str(stage), "--sandbox-path", entry)
        mount = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\probe_guest_channels.ps1")
        if mount != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError("Le montage ou les canaux du bac ne sont pas attestés.")
        report["isolation"] = {"read_only_input": True, "declared_disabled_channels": CHANNELS, "probe": channels}
        harness = f"{POWERSHELL} -File {entry}\\run_tasks_validation.ps1 -Tag {tag} -Phase"

        localize, generate, verify = plan["steps"]
        require_step_permission(localize, goal, active_sandboxes() == [sandbox])
        faulty = decode_oracle(guest_exit(sandbox, f"{harness} localize"))
        report["trace"].append({"id": localize["id"], "result": faulty})
        report["protected_filters"] = [name for name, passed in faulty["filters"].items() if passed]
        require_step_permission(verify, goal, active_sandboxes() == [sandbox])
        reference = decode_oracle(guest_exit(sandbox, f"{harness} reference"))
        report["reference"] = reference
        if (all(faulty["filters"].values()) or not faulty["sqlite_unchanged"]
                or not all(reference["filters"].values()) or not reference["sqlite_unchanged"]):
            raise RuntimeError("La régression ou le témoin indépendant est invalide.")
        write_report(output, report)

        def run_attempt(attempt, previous):
            require_step_permission(generate, goal, active_sandboxes() == [sandbox])
            previous_checks = previous[1] if previous is not None else None
            prompt = repair_prompt(
                goal["user_intent"], source, faulty, sqlite_schema=sqlite_schema, previous_checks=previous_checks,
            )
            model_work = output / f"attempt-{attempt}"
            model_work.mkdir()
            timeout = configuration["http_timeout_s_by_attempt"][attempt - 1]
            process = {
                "feedback_from_attempt": attempt - 1 if previous is not None else None,
                "target_filters": failed_filters(faulty if previous_checks is None else previous_checks),
                "http_timeout_s": timeout,
                "diff_applied": False,
            }
            report["trace"].append({"id": generate["id"], "attempt": attempt, "result": process})
            (model_work / "prompt.txt").write_text(prompt, encoding="utf-8")
            with execution_limits(None, configuration["cpu_threads"], configuration["model_ram_mib"]):
                response, startup, generation = infer(
                    repair, model_work, prompt, SEED, max_tokens=MAX_TOKENS, http_timeout_s=timeout,
                )
            (model_work / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            choice = response["choices"][0]
            process.update(startup_s=round(startup, 3), generation_s=round(generation, 3),
                           finish_reason=choice.get("finish_reason"))
            proposal = replace_definition(source, choice["message"].get("content") or "")
            artifact = model_work / "proposal.diff"
            artifact.write_bytes(proposal.diff.encode("utf-8"))
            process.update(diff_sha256=file_hash(artifact), ast_sha256=proposal.ast_sha256)
            if previous is not None:
                process["distinct_proposal"] = distinct_proposal(proposal, previous[0])
                if not process["distinct_proposal"]:
                    raise RuntimeError("La seconde proposition répète le diff ou la structure Python du premier.")
            staged = stage / "proposal" / f"attempt-{attempt}"
            staged.mkdir(parents=True)
            shutil.copyfile(artifact, staged / "proposal.diff")
            (staged / "repair.sha256").write_text(proposal.file_sha256, encoding="ascii")

            require_step_permission(generate, goal, active_sandboxes() == [sandbox])
            code = guest_exit(sandbox, f"{harness} apply -Attempt {attempt}")
            process["guest_apply_exit_code"] = code
            if code != 0x4602:
                raise RuntimeError(f"Le diff Rbitnet a été refusé dans le bac ({code}).")
            process.update(diff_applied=True, git_apply_check=True, guest_sha256_verified=True)
            require_step_permission(verify, goal, active_sandboxes() == [sandbox])
            checks = decode_oracle(guest_exit(sandbox, f"{harness} verify -Attempt {attempt}"))
            checks["failed_targets"] = [name for name in process["target_filters"] if not checks["filters"][name]]
            checks["baseline_filter_regressions"] = baseline_filter_regressions(faulty, checks)
            if previous is not None and checks["baseline_filter_regressions"]:
                checks["rejection_reason"] = "baseline_filter_regression"
            report["trace"].append({"id": verify["id"], "attempt": attempt, "result": checks})
            if any(file_hash(stage / "case" / path) != digest for path, digest in fixture_hashes.items()):
                raise RuntimeError("Intégrité des entrées protégées non attestée.")
            report["isolation"]["fixture_unchanged"] = True
            write_report(output, report)
            return proposal, checks

        report["accepted_attempt"] = evaluate_proposals(run_attempt, faulty)
        report["status"] = "passed" if report["accepted_attempt"] is not None else "failed"
    except (OSError, RuntimeError, ValueError, SyntaxError, KeyError, PlanningError, subprocess.SubprocessError) as error:
        report.update(status="failed", error=str(error))
    finally:
        if sandbox:
            try:
                if sandbox in active_sandboxes():
                    wsb("stop", "--id", sandbox)
                report["sandbox_stopped"] = sandbox not in active_sandboxes()
                if not report["sandbox_stopped"]:
                    raise RuntimeError("Arrêt du bac non confirmé.")
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
                report.update(status="failed", cleanup_error=str(error))
        report["wall_s"] = round(perf_counter() - wall, 3)
        write_report(output, report)
    return report
