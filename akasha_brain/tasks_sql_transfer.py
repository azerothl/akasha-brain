"""Transfert Tâches par réparation des clauses SQL du filtre, hors évolution."""

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from time import perf_counter
from uuid import UUID, uuid4

from bench.harness.tasks_oracle_deltas import decode_oracle
from bench.run_guided_repair import BENCH, CHECKPOINTS, file_hash, write_report, wsb
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .notes_repair import RbitnetPaths, stage_git
from .notes_sandbox import CHANNELS, POWERSHELL, active_sandboxes, guest_exit, read_profile, require_step_permission, wait_for_guest
from .planning import PlanningError, TASKS_ENVIRONMENT, compile_goal, load_catalog
from .rbitnet_session import server
from .tasks_transfer import GUEST_FILES, failed_filters, frozen_inputs, verification_feedback

VERSION = "1.3.0"
NON_THINKING_TEMPLATE = (
    r"{% for m in messages %}{{ '<|im_start|>' ~ m.role ~ '\n' ~ m.content ~ '<|im_end|>\n' }}"
    r"{% endfor %}{{ '<|im_start|>assistant\n<think>\n\n</think>\n\n' }}"
)
CONFIGURATION = {"seed": 742, "max_tokens": 144, "attempts": 2, "threads": 8, "ram_mib": 8192,
                 "vram_mib": 8192, "timeout_s": 160,
                 "chat_template": NON_THINKING_TEMPLATE, "stop": ["<|im_end|>", "\n\n"]}
FORBIDDEN_SQL = re.compile(
    r";|--|/\*|\*/|\?|[:@$][A-Za-z_]|\b(?:select|union|intersect|except|pragma|attach|detach|create|drop|alter|"
    r"insert|update|delete|replace|returning|load_extension)\b", re.IGNORECASE,
)
SQL_LITERAL = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|\[[^\]]*\]|`[^`]*`""")


def lock_document(library: Path | None) -> dict:
    imports = {file: file_hash(BENCH.parent / file) for file in (
        "akasha_brain/tasks_sql_transfer.py", "akasha_brain/rbitnet_session.py", "akasha_brain/model_resources.py",
    )}
    return {"version": VERSION, "inputs": {**frozen_inputs(), **imports}, "runtime": CONFIGURATION,
            "weights_and_engine": CHECKPOINTS, "cuda_library_sha256": file_hash(library) if library else None}


def clause_nodes(source: str) -> dict[str, ast.Constant]:
    declarations = [row.value for row in ast.parse(source).body
                    if isinstance(row, ast.Assign) and len(row.targets) == 1
                    and isinstance(row.targets[0], ast.Name) and row.targets[0].id == "FILTER_CLAUSES"]
    if len(declarations) != 1 or not isinstance(declarations[0], ast.Dict):
        raise ValueError("Une table FILTER_CLAUSES est requise.")
    table = declarations[0]
    result = {}
    for key, value in zip(table.keys, table.values):
        if (not isinstance(key, ast.Constant) or not isinstance(key.value, str)
                or not isinstance(value, ast.Constant) or not isinstance(value.value, str)
                or key.value in result):
            raise ValueError("Les filtres doivent avoir des noms et des clauses littérales uniques.")
        result[key.value] = value
    return result


def response_clause(answer: str) -> str:
    # Lire le premier bloc complet avant tout contrôle ou choix fondé sur le verdict.
    match = re.match(r"```(?:sql)?\s*(.*?)\s*```", answer.strip(), flags=re.I | re.S)
    clause = match.group(1).strip() if match else answer.strip()
    syntax = SQL_LITERAL.sub("''", clause)
    if (not re.match(r"(?:WHERE\s+|ORDER\s+BY\s+)", clause, re.I)
            or FORBIDDEN_SQL.search(syntax) or any(ord(char) < 32 and char not in "\t\n\r" for char in clause)):
        raise ValueError("Une clause WHERE ou ORDER BY sans requête, paramètre ni commentaire est requise.")
    return clause


def render_patch(source: str, replacements: dict[str, str]) -> tuple[str, str]:
    entries = clause_nodes(source)
    lines = source.encode("utf-8").splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    operations = []
    for target, clause in replacements.items():
        node = entries[target]
        begin = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        operations.append((begin, end, repr(clause).encode("utf-8")))
    encoded = source.encode("utf-8")
    for begin, end, replacement in sorted(operations, reverse=True):
        encoded = encoded[:begin] + replacement + encoded[end:]
    updated = encoded.decode("utf-8")
    updated_entries = clause_nodes(updated)
    if ({key: node.value for key, node in updated_entries.items()}
            != {key: replacements.get(key, value.value) for key, value in entries.items()}):
        raise ValueError("La réécriture ne correspond pas aux clauses sélectionnées.")
    diff = "".join(unified_diff(source.splitlines(keepends=True), updated.splitlines(keepends=True),
                                fromfile="a/repair.py", tofile="b/repair.py"))
    if not diff:
        raise ValueError("La clause proposée ne modifie pas le module.")
    return diff, sha256(encoded).hexdigest()


def prompt(intent, schema, source, target, clause, prior):
    feedback = f"\nPrevious check:\n{prior}\n" if prior else ""
    return (
        f"Task: {intent}\n\n"
        f"Repair only the filter {target!r}. The independent check found that filter incorrect.\n"
        f"Current clause: {clause}\n"
        "Return ONLY the SQL suffix starting with WHERE or ORDER BY, optionally in a sql fenced block. "
        "The SELECT and FROM prefix, output columns, other filters, and the Python code are fixed. "
        "Do not return a full SELECT, a semicolon, comments or placeholders. Preserve the requested order.\n"
        f"{feedback}\nSQLite schema:\n{schema}\n\nPython module:\n{source}"
    )


@contextmanager
def trace_step(report, step, **metadata):
    started = perf_counter()
    row = {"id": step["id"], "started_at": datetime.now(timezone.utc).isoformat(), "status": "failed", **metadata}
    report["trace"].append(row)
    try:
        yield row
    finally:
        row["wall_s"] = round(perf_counter() - started, 3)


def run(case: Path, frozen: dict, runtime: Path, output: Path, paths: RbitnetPaths, backend: str, library: Path | None) -> dict:
    observed = lock_document(library if backend == "cuda" else None)
    if backend == "cpu":
        observed["cuda_library_sha256"] = frozen["cuda_library_sha256"]
    if observed != frozen:
        raise ValueError("Le graphe SQL ou ses dépendances diffèrent du gel.")
    paths.verify()
    goal = json.loads((case / "goal.json").read_bytes())
    plan = compile_goal(goal, load_catalog(), rbitnet=True)
    if plan["environment_id"] != TASKS_ENVIRONMENT:
        raise ValueError("Objectif Tâches requis.")
    plan.update(graph_id="tasks-rbitnet-sql", graph_version=VERSION)
    plan["repair_context"] = {"sqlite_schema": "schema.sql", "rewrite": "failed_filter_sql_literal_only"}
    output.mkdir(parents=True)
    report = {"graph": plan, "status": "running", "evolution": "excluded", "inference_backend": backend,
              "freeze_sha256": sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest(),
              "rbitnet": frozen["runtime"], "trace": [], "accepted_attempt": None,
              "started_at": datetime.now(timezone.utc).isoformat(), "repair": {"model": paths.model.name}}
    start = perf_counter()
    sandbox = None
    try:
        if active_sandboxes():
            raise RuntimeError("Une session Windows Sandbox est déjà active.")
        stage = output / "input"
        stage.mkdir()
        staged = stage / "case"
        shutil.copytree(case, staged, ignore=shutil.ignore_patterns("__pycache__"))
        source = (staged / "repair.py").read_text(encoding="utf-8")
        (staged / "repair.py").write_bytes(source.encode("utf-8"))
        schema = (staged / "schema.sql").read_text(encoding="utf-8")
        filters = clause_nodes(source)
        fingerprints = {p.relative_to(staged).as_posix(): file_hash(p) for p in staged.rglob("*") if p.is_file()}
        report["case_sha256"] = fingerprints
        shutil.copytree(runtime, stage / "python")
        report["git"] = stage_git(stage)
        for name in GUEST_FILES:
            shutil.copyfile(BENCH / "harness" / name, stage / name)
        tag = secrets.token_hex(4)
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        entry = fr"C:\AkashaGuidedInput-{tag}"
        sandbox = str(uuid4())
        report["sandbox_id"] = sandbox
        if str(UUID(wsb("start", "--id", sandbox, "--config", read_profile())["Id"])) != sandbox:
            raise RuntimeError("Identifiant du bac inattendu.")
        wait_for_guest(sandbox)
        wsb("share", "--id", sandbox, "--host-path", str(stage), "--sandbox-path", entry)
        mount = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\probe_guest_channels.ps1")
        if mount != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError("Les protections du bac ne sont pas attestées.")
        report["isolation"] = {"read_only_input": True, "disabled_channels": CHANNELS, "probe": channels}
        harness = f"{POWERSHELL} -File {entry}\\run_tasks_validation.ps1 -Tag {tag} -Phase"
        localize, generate, verify = plan["steps"]

        def guest(phase, step, suffix=""):
            require_step_permission(step, goal, active_sandboxes() == [sandbox])
            return guest_exit(sandbox, f"{harness} {phase}{suffix}")

        with trace_step(report, localize) as location:
            initial = decode_oracle(guest("localize", localize))
            location.update(result=initial, authorization="allowed")
            reference = decode_oracle(guest("reference", verify))
            report["reference"] = reference
            targets = failed_filters(initial)
            if set(filters) != set(initial["filters"]) or not targets or not initial["sqlite_unchanged"]:
                raise ValueError("La régression ou la table de filtres est incompatible.")
            if not all(reference["filters"].values()) or not reference["sqlite_unchanged"]:
                raise ValueError("Le témoin indépendant échoue.")
            location["status"] = "passed"
        report["protected_filters"] = [key for key in filters if key not in targets]
        write_report(output, report)
        model_work = output / "model"
        model_work.mkdir()
        with server(paths, model_work, backend=backend, cuda_library=library,
                    threads=CONFIGURATION["threads"], ram_mib=CONFIGURATION["ram_mib"],
                    vram_mib=CONFIGURATION["vram_mib"], template=NON_THINKING_TEMPLATE) as model:
            meta = model.metadata.get("metadata", {})
            report["model"] = {"id": model.metadata["id"], "startup_s": model.startup_s, "residency": model.residency,
                               "backend": meta.get("backend"), "backend_accelerated": meta.get("backend_accelerated")}
            prior, previous_diff = None, None
            for index in range(1, CONFIGURATION["attempts"] + 1):
                row = {"targets": targets, "inferences": [], "diff_applied": False,
                       "seed": CONFIGURATION["seed"], "residency": model.residency}
                replacements = {}
                with trace_step(report, generate, attempt=index, result=row) as generation:
                    require_step_permission(generate, goal, active_sandboxes() == [sandbox])
                    generation["authorization"] = "allowed"
                    attempt = output / f"attempt-{index}"
                    attempt.mkdir()
                    try:
                        for number, target in enumerate(targets, start=1):
                            instruction = prompt(goal["user_intent"], schema, source, target, filters[target].value, prior)
                            (attempt / f"prompt-{number}.txt").write_text(instruction, encoding="utf-8")
                            response, elapsed = model.chat([{"role": "user", "content": instruction}],
                                                           seed=CONFIGURATION["seed"], max_tokens=CONFIGURATION["max_tokens"],
                                                           stop=CONFIGURATION["stop"], timeout=CONFIGURATION["timeout_s"])
                            (attempt / f"response-{number}.json").write_text(json.dumps(response, ensure_ascii=False),
                                                                            encoding="utf-8")
                            choice = response["choices"][0]
                            row["inferences"].append({"filter": target, "wall_s": elapsed,
                                                      "finish_reason": choice.get("finish_reason")})
                            replacements[target] = response_clause(choice["message"].get("content") or "")
                        diff, expected = render_patch(source, replacements)
                        if diff == previous_diff:
                            raise ValueError("La seconde proposition répète la première.")
                    except ValueError as error:
                        row["rejected"] = str(error)
                        prior = str(error)
                    else:
                        previous_diff = diff
                        artifact = stage / "proposal" / f"attempt-{index}"
                        artifact.mkdir(parents=True)
                        (artifact / "proposal.diff").write_bytes(diff.encode("utf-8"))
                        (artifact / "repair.sha256").write_text(expected, encoding="ascii")
                        code = guest("apply", generate, f" -Attempt {index}")
                        if code != 0x4602:
                            raise RuntimeError(f"Le bac a refusé le diff ({code}).")
                        row.update(diff_applied=True, git_apply_check=True, guest_sha256_verified=True, clauses=replacements)
                        generation["status"] = "passed"
                write_report(output, report)
                if not row["diff_applied"]:
                    continue
                with trace_step(report, verify, attempt=index) as verification:
                    verdict = decode_oracle(guest("verify", verify, f" -Attempt {index}"))
                    verification.update(result=verdict, authorization="allowed")
                    if any(file_hash(staged / name) != digest for name, digest in fingerprints.items()):
                        raise RuntimeError("L’intégrité du cas réservé est rompue.")
                    report["isolation"]["fixture_unchanged"] = True
                    if all(verdict["filters"].values()) and verdict["sqlite_unchanged"]:
                        verification["status"] = "passed"
                if verification["status"] == "passed":
                    report.update(status="passed", accepted_attempt=index)
                    break
                prior = verification_feedback(verdict)
                write_report(output, report)
            (model_work / "after.prom").write_text(model.request("/metrics"), encoding="utf-8")
    except PlanningError as error:
        report.update(status="failed", error=error.error.as_dict())
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report.update(status="failed", error=AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(error)).as_dict())
    finally:
        if report["status"] == "running":
            report["status"] = "failed"
        if sandbox:
            try:
                if sandbox in active_sandboxes():
                    wsb("stop", "--id", sandbox)
                report["sandbox_stopped"] = sandbox not in active_sandboxes()
                if not report["sandbox_stopped"]:
                    report.update(status="failed", cleanup_error="Arrêt du bac non confirmé.")
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
                report.update(status="failed", cleanup_error=str(error))
        report["wall_s"] = round(perf_counter() - start, 3)
        write_report(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--output", required=True, type=Path)
    replay = sub.add_parser("run")
    for name in ("case", "freeze", "python-runtime", "output"):
        replay.add_argument(f"--{name}", required=True, type=Path)
    replay.add_argument("--rbitnet", nargs=3, required=True, type=Path)
    replay.add_argument("--backend", choices=("cpu", "cuda"), default="cpu")
    for child in (freeze, replay):
        child.add_argument("--cuda-library", type=Path)
    args = parser.parse_args()
    library = args.cuda_library.resolve(strict=True) if args.cuda_library else None
    if args.action == "freeze":
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(lock_document(library), stream, ensure_ascii=False, indent=2)
        return 0
    if args.backend == "cuda" and library is None:
        parser.error("--backend cuda exige --cuda-library")
    result = run(args.case.resolve(), json.loads(args.freeze.read_bytes()), args.python_runtime.resolve(),
                 args.output.resolve(), RbitnetPaths(*(path.resolve() for path in args.rbitnet)), args.backend, library)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
