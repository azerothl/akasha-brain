"""Compare le spécialiste SQL aux mesures de référence sur les deux cas de développement."""

import argparse
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
from time import perf_counter
from uuid import UUID, uuid4

from akasha_brain import tasks_sql_specialist as specialist
from akasha_brain import tasks_sql_specialist_v2 as specialist_v2
from akasha_brain import tasks_sql_specialist_v3 as specialist_v3
from akasha_brain.notes_repair import RbitnetPaths, stage_git
from akasha_brain.notes_sandbox import (
    CHANNELS, POWERSHELL, active_sandboxes, guest_exit, read_profile, require_step_permission, wait_for_guest,
)
from akasha_brain.planning import PlanningError, TASKS_ENVIRONMENT, compile_goal, load_catalog
from akasha_brain.rbitnet_session import server
from akasha_brain.tasks_sql_transfer import CONFIGURATION, NON_THINKING_TEMPLATE, clause_nodes, lock_document, render_patch, trace_step
from akasha_brain.tasks_transfer import GUEST_FILES, failed_filters, verification_feedback
from bench.harness.tasks_oracle_deltas import decode_oracle
from bench.run_guided_repair import BENCH, file_hash, write_report, wsb
from bench.run_phase4_tasks_baseline import FILES, FIXTURES, LOCK, measure, prepare_case
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

REFERENCE = BENCH / "results" / "phase4-tasks-baseline-v1.json"
REFERENCE_V1 = BENCH / "results" / "phase4-tasks-specialist-v1.json"
REFERENCE_V2 = BENCH / "results" / "phase4-tasks-specialist-v2.json"
COVERAGE = FIXTURES / "coverage-v2.json"
GRAPH = "tasks-rbitnet-sql-structured"
RECHECK_TIMEOUT_S = 300


@contextmanager
def sandbox(stage: Path, report: dict):
    identity = str(uuid4())
    report["sandbox_id"] = identity
    try:
        if str(UUID(wsb("start", "--id", identity, "--config", read_profile())["Id"])) != identity:
            raise RuntimeError("Identifiant du bac inattendu.")
        wait_for_guest(identity)
        tag = secrets.token_hex(4)
        guest_path = fr"C:\AkashaGuidedInput-{tag}"
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        wsb("share", "--id", identity, "--host-path", str(stage), "--sandbox-path", guest_path)
        mount = guest_exit(identity, f"{POWERSHELL} -File {guest_path}\\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(identity, f"{POWERSHELL} -File {guest_path}\\probe_guest_channels.ps1")
        if mount != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError("Les protections du bac ne sont pas attestées.")
        report["isolation"] = {"read_only_input": True, "disabled_channels": CHANNELS, "probe": channels}
        yield identity, f"{POWERSHELL} -File {guest_path}\\run_tasks_validation.ps1 -Tag {tag} -Phase"
    finally:
        if identity in active_sandboxes():
            wsb("stop", "--id", identity)
        report["sandbox_stopped"] = identity not in active_sandboxes()
        if not report["sandbox_stopped"]:
            raise RuntimeError("Arrêt du bac dédié non confirmé.")


def run_case(case_folder: Path, runtime: Path, output: Path, paths: RbitnetPaths,
             *, timeout_s: int = CONFIGURATION["timeout_s"], required: dict | None = None,
             v3: bool = False) -> dict:
    goal = json.loads((case_folder / "goal.json").read_bytes())
    graph = compile_goal(goal, load_catalog(), rbitnet=True)
    if graph["environment_id"] != TASKS_ENVIRONMENT or paths.backend != "cpu":
        raise ValueError("Le spécialiste exige le banc Tâches et les poids Rbitnet CPU vérifiés.")
    if v3 and required is None:
        raise ValueError("Le spécialiste v3 exige un contrat de couverture.")
    version = specialist_v3.VERSION if v3 else specialist.VERSION if required is None else specialist_v2.VERSION
    graph.update(graph_id=GRAPH, graph_version=version)
    graph["repair_context"] = {"rewrite": "failed_filter_sql_literal_only",
                               "output": f"structured_sql_v{version[0]}"}
    output.mkdir(parents=True)
    started = perf_counter()
    report = {"graph": graph, "status": "running", "inference_backend": "cpu", "evolution": "excluded",
              "rbitnet": {**CONFIGURATION, "timeout_s": timeout_s}, "trace": [], "accepted_attempt": None}
    try:
        if active_sandboxes():
            raise RuntimeError("Une session Windows Sandbox est déjà active.")
        report["weights_and_engine"] = paths.verify()
        stage = output / "input"
        staged = stage / "case"
        shutil.copytree(case_folder, staged)
        module = staged / "repair.py"
        source = module.read_text(encoding="utf-8")
        module.write_bytes(source.encode("utf-8"))
        schema = (staged / "schema.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(":memory:")) as structure:
            structure.execute(schema)
            columns = frozenset(row[1] for row in structure.execute("PRAGMA table_info(jobs)"))
        if not columns:
            raise ValueError("Le schéma synthétique doit exposer la table jobs.")
        filters = clause_nodes(source)
        report["case_sha256"] = {p.name: file_hash(p) for p in staged.iterdir()}
        shutil.copytree(runtime, stage / "python")
        report["git"] = stage_git(stage)
        for name in GUEST_FILES:
            shutil.copyfile(BENCH / "harness" / name, stage / name)
        localize, generate, verify = graph["steps"]

        with sandbox(stage, report) as (identity, runner):
            def guest(phase: str, step: dict, attempt: int = 1) -> int:
                require_step_permission(step, goal, active_sandboxes() == [identity])
                return guest_exit(identity, f"{runner} {phase} -Attempt {attempt}")

            with trace_step(report, localize) as located:
                initial = decode_oracle(guest("localize", localize))
                witness = decode_oracle(guest("reference", verify))
                targets = failed_filters(initial)
                located.update(result=initial, authorization="allowed")
                report["reference"] = witness
                if (set(filters) != set(initial["filters"]) or len(targets) != 1 or not initial["sqlite_unchanged"]
                        or not all(witness["filters"].values()) or not witness["sqlite_unchanged"]):
                    raise ValueError("Un filtre en échec et un témoin complet sont requis.")
                located["status"] = "passed"
            target = targets[0]
            write_report(output, report)
            model_folder = output / "model"
            model_folder.mkdir()
            feedback = previous_diff = None
            with server(paths, model_folder, threads=CONFIGURATION["threads"], ram_mib=CONFIGURATION["ram_mib"],
                        template=NON_THINKING_TEMPLATE) as model:
                report["model"] = {"id": model.metadata["id"], "startup_s": model.startup_s, "residency": model.residency}
                for index in range(1, CONFIGURATION["attempts"] + 1):
                    generated = {"targets": targets, "inferences": [], "diff_applied": False}
                    with trace_step(report, generate, attempt=index, result=generated) as step:
                        require_step_permission(generate, goal, active_sandboxes() == [identity])
                        step["authorization"] = "allowed"
                        work = output / f"attempt-{index}"
                        work.mkdir()
                        if required is None:
                            instruction = specialist.specialist_prompt(goal["user_intent"], schema, source,
                                                                       target, filters[target].value, feedback)
                        elif v3:
                            instruction = specialist_v3.specialist_prompt(goal["user_intent"], target, required, feedback)
                        else:
                            instruction = specialist_v2.specialist_prompt(goal["user_intent"], schema, target,
                                                                            filters[target].value, required, feedback)
                        (work / "prompt.txt").write_text(instruction, encoding="utf-8")
                        response, elapsed = model.chat([{"role": "user", "content": instruction}],
                                                       seed=CONFIGURATION["seed"], max_tokens=CONFIGURATION["max_tokens"],
                                                       stop=CONFIGURATION["stop"], timeout=timeout_s)
                        (work / "response.json").write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
                        choice = response["choices"][0]
                        generated["inferences"].append({"filter": target, "wall_s": elapsed,
                                                        "finish_reason": choice.get("finish_reason")})
                        try:
                            answer = choice["message"].get("content") or ""
                            if required is None:
                                plan, clause = specialist.decode_plan(answer, columns)
                                generated["structured_plan"] = plan
                            else:
                                if v3:
                                    flat, repaired = specialist_v3.parse_response(answer)
                                    generated.update(flat_plan=flat, json_extra_brace_removed=repaired)
                                    plan = specialist_v3.expand_plan(flat, required)
                                else:
                                    plan = specialist_v2.parse_plan(answer)
                                generated["structured_plan"] = plan
                                clause = specialist_v2.compile_checked(plan, required, columns)
                                generated["coverage"] = {"status": "passed"}
                            diff, checksum = render_patch(source, {target: clause})
                            if diff == previous_diff:
                                raise ValueError("La proposition répète le précédent diff.")
                        except specialist_v2.CoverageError as error:
                            generated["coverage"] = {"status": "rejected", "issues": error.issues}
                            feedback = generated["rejected"] = str(error)
                        except ValueError as error:
                            feedback = generated["rejected"] = str(error)
                        else:
                            previous_diff = diff
                            patch = stage / "proposal" / f"attempt-{index}"
                            patch.mkdir(parents=True)
                            (patch / "proposal.diff").write_bytes(diff.encode("utf-8"))
                            (patch / "repair.sha256").write_text(checksum, encoding="ascii")
                            if guest("apply", generate, index) != 0x4602:
                                raise RuntimeError("Le bac a refusé le diff généré.")
                            generated.update(diff_applied=True, git_apply_check=True, guest_sha256_verified=True,
                                             clauses={target: clause})
                            step["status"] = "passed"
                    write_report(output, report)
                    if not generated["diff_applied"]:
                        continue
                    with trace_step(report, verify, attempt=index) as checked:
                        verdict = decode_oracle(guest("verify", verify, index))
                        checked.update(result=verdict, authorization="allowed")
                        if all(verdict["filters"].values()) and verdict["sqlite_unchanged"]:
                            checked["status"] = "passed"
                    if checked["status"] == "passed":
                        report.update(status="passed", accepted_attempt=index)
                        break
                    feedback = verification_feedback(verdict)
                    write_report(output, report)
            if {p.name: file_hash(p) for p in staged.iterdir()} != report["case_sha256"]:
                raise RuntimeError("L'intégrité du cas de développement est rompue.")
    except PlanningError as error:
        report.update(status="failed", error=error.error.as_dict())
    except (OSError, RuntimeError, ValueError, KeyError, sqlite3.Error, subprocess.SubprocessError) as error:
        failure = AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(error))
        report.update(status="failed", error=failure.as_dict())
    finally:
        if report["status"] == "running":
            report["status"] = "failed"
        report["wall_s"] = round(perf_counter() - started, 3)
        write_report(output, report)
    return report


def reference_path(v2: bool, v3: bool) -> Path:
    return REFERENCE_V2 if v3 else REFERENCE_V1 if v2 else REFERENCE


def inputs(*, v2: bool = False, v3: bool = False) -> dict:
    result = {"protocol_sha256": file_hash(LOCK), "reference_sha256": file_hash(reference_path(v2, v3)),
              "fixture_sha256": {name: file_hash(FIXTURES / name) for name in FILES},
              "specialist_sha256": file_hash(Path(specialist.__file__)), "runner_sha256": file_hash(Path(__file__))}
    if v2 or v3:
        result["coverage_sha256"] = file_hash(COVERAGE)
        result["specialist_v2_sha256"] = file_hash(Path(specialist_v2.__file__))
    if v3:
        result["specialist_v3_sha256"] = file_hash(Path(specialist_v3.__file__))
    return result


def measure_pair(report: dict, case: dict, reference: dict, seen: set) -> dict:
    measured = measure(report, case)
    measured["same_witness_and_initial"] = measured["witness"] == reference["witness"] and measured["initial"] == reference["initial"]
    measured["distinct_sandbox"] = bool(measured["sandbox_id"]) and measured["sandbox_id"] not in seen
    measured["http_timeout_s"] = report["rbitnet"]["timeout_s"]
    for step in report["trace"]:
        if step["id"] != "generate_diff":
            continue
        generated = step.get("result", {})
        attempt = measured["attempts"][step["attempt"]]
        for key in ("flat_plan", "json_extra_brace_removed", "structured_plan", "coverage"):
            if key in generated:
                attempt[key] = generated[key]
        if "clauses" in generated:
            attempt["compiled_clause"] = generated["clauses"][case["target"]]
    return measured


def record_totals(result: dict) -> None:
    finals = [pair["candidate"][-1] for pair in result["runs"].values()]
    complete = all(run["evaluated"] and run["same_witness_and_initial"] and run["distinct_sandbox"] for run in finals)
    result.update(status="passed" if complete else "incomplete",
                  evaluated_cases=sum(run["evaluated"] for run in finals),
                  accepted_first_attempt=sum(run["accepted_attempt"] == 1 for run in finals),
                  accepted_after_repair=sum(run["accepted_attempt"] is not None for run in finals))


def coverage_contracts(cases: list[dict]) -> dict:
    document = json.loads(COVERAGE.read_bytes())
    contracts = document["cases"]
    if document["version"] != 1 or set(contracts) != {case["id"] for case in cases}:
        raise ValueError("Le contrat de couverture doit correspondre aux cas de développement.")
    for case in cases:
        contract = contracts[case["id"]]
        if (contract["target"] != case["target"]
                or contract["intent_sha256"] != sha256(case["intent"].encode()).hexdigest()):
            raise ValueError("La couverture ne correspond pas à la consigne figée.")
        specialist_v2.verify_coverage(contract["plan"], contract["plan"])
    return {name: contract["plan"] for name, contract in contracts.items()}


def compare(runtime: Path, paths: RbitnetPaths, output: Path, *, v2: bool = False, v3: bool = False) -> dict:
    checked = v2 or v3
    checksums = inputs(v2=v2, v3=v3)
    reference = json.loads(reference_path(v2, v3).read_bytes())
    frozen = json.loads(LOCK.read_bytes())
    pinned = reference["inputs"] if checked else reference
    if ({**lock_document(None), "cuda_library_sha256": frozen["cuda_library_sha256"]} != frozen
            or reference["status"] != "passed" or reference["backend"] != "cpu"
            or pinned["protocol_sha256"] != checksums["protocol_sha256"]
            or pinned["fixture_sha256" if checked else "fixtures_sha256"] != checksums["fixture_sha256"]
            or (checked and pinned["specialist_sha256"] != checksums["specialist_sha256"])
            or (v3 and any(pinned[key] != checksums[key] for key in ("coverage_sha256", "specialist_v2_sha256")))):
        raise RuntimeError("La référence archivée et les scénarios doivent correspondre exactement.")
    cases = json.loads((FIXTURES / "cases.json").read_bytes())["cases"]
    required = coverage_contracts(cases) if checked else {}
    version = specialist_v3.VERSION if v3 else specialist_v2.VERSION if v2 else specialist.VERSION
    initial_timeout = RECHECK_TIMEOUT_S if checked else CONFIGURATION["timeout_s"]
    result = {"status": "running", "graph": f"{GRAPH}@{version}", "backend": "cpu",
              "reference_graph": reference["graph"], "runtime": {**CONFIGURATION, "timeout_s": initial_timeout},
              "inputs": checksums, "runs": {}}
    output.mkdir(parents=True)
    write_report(output, result)
    reference_runs = "candidate" if checked else "executions"
    seen = {trial["sandbox_id"] for row in reference["runs"].values() for trial in row[reference_runs]}
    for case in cases:
        tag = case["id"]
        old = reference["runs"][tag][reference_runs][-1]
        if not old["evaluated"] or not old["sandbox_stopped"] or old["evolution"] != "excluded":
            raise RuntimeError("Un cas de référence est incomplet.")
        folder = output / "cases" / tag
        prepare_case(case, folder)
        pair = {"target": case["target"], "reference": old, "candidate": []}
        result["runs"][tag] = pair
        timeout_s = initial_timeout
        for label in (tag, f"{tag}-recheck"):
            print(f"Spécialiste CPU {label}, cible {case['target']}", flush=True)
            report = run_case(folder, runtime, output / label, paths, timeout_s=timeout_s, required=required.get(tag), v3=v3)
            measured = measure_pair(report, case, old, seen)
            pair["candidate"].append(measured)
            pair["total_delta_s"] = round(measured["total_s"] - old["total_s"], 3)
            write_report(output, result)
            print(json.dumps({key: measured[key] for key in ("evaluated", "status", "accepted_attempt", "total_s")},
                             ensure_ascii=False), flush=True)
            seen.add(measured["sandbox_id"])
            error = (report.get("error") or {}).get("message", "")
            if not report.get("sandbox_stopped"):
                break
            if timeout_s < RECHECK_TIMEOUT_S and measured["same_witness_and_initial"] and error == "timed out":
                timeout_s = RECHECK_TIMEOUT_S
            elif report["trace"] or not error.startswith("wsb start (") or "timed out" not in error:
                break
    if inputs(v2=v2, v3=v3) != checksums:
        raise RuntimeError("Le spécialiste ou ses entrées ont changé pendant la comparaison.")
    record_totals(result)
    result.update(reference_first_attempt=reference["accepted_first_attempt"],
                  reference_after_repair=reference["accepted_after_repair"])
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", nargs=3, type=Path, required=True, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--output", type=Path, required=True)
    version = parser.add_mutually_exclusive_group()
    version.add_argument("--v2", action="store_true", help="Vérifie la couverture et compare aux résultats v1.")
    version.add_argument("--v3", action="store_true", help="Simplifie le plan vérifié et compare aux résultats v2.")
    args = parser.parse_args()
    paths = RbitnetPaths(*(path.resolve(strict=True) for path in args.rbitnet))
    result = compare(args.runtime.resolve(strict=True), paths, args.output.resolve(), v2=args.v2, v3=args.v3)
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
