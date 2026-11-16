"""Compare Path A au routage déterministe et rejoue les autres familles."""

import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from akasha_brain.notes_evolution import evidence
from akasha_brain.tasks_gate import evaluate, signals
from akasha_brain.tasks_routing import SPECIALIST, Registry
from bench.run_guided_repair import write_report
from bench.run_notes_link_promotion import verify_chain
from bench.run_phase4_tasks_reserved import FIXTURES, ROOT, prepare
from bench.run_phase4_tasks_routing import cli, preserve_family_routes, project_check


CASES = (
    ("specialist_eligible", "ready", signals("specialist")),
    ("reference_selected", "ready", signals("reference")),
    ("ambiguous_route", "abstain", signals("specialist", certain=False)),
    ("permission_denied", "blocked", signals("specialist", authorized=False)),
    ("missing_context", "blocked", signals("specialist", context=False)),
    ("missing_capability", "blocked", signals("reference", capability=False)),
    ("exhausted_budget", "blocked", signals("specialist", budget=0)),
    ("outside_risk", "blocked", signals("specialist", risk=1)),
    ("missing_confirmation", "blocked", signals("reference", confirmation_needed=True)),
    ("confirmed", "ready", signals("reference", confirmation_needed=True, confirmation_given=True)),
    ("ambiguous_but_denied", "blocked", signals("specialist", certain=False, authorized=False)),
    ("budget_available", "ready", signals("specialist", budget=1)),
)


def summary(rows: list[dict], arm: str) -> dict:
    return {
        "correct": sum(row["expected"] == row[arm] for row in rows),
        "false_ready": sum(row["expected"] != "ready" and row[arm] == "ready" for row in rows),
        "false_abstain": sum(row["expected"] != "abstain" and row[arm] == "abstain" for row in rows),
        "false_blocked": sum(row["expected"] != "blocked" and row[arm] == "blocked" for row in rows),
        "median_us": median(row[f"{arm}_us"] for row in rows),
    }


def run(runtime: Path, wheel_request: Path, paths: list[Path], output: Path) -> dict:
    output.mkdir(parents=True)
    registry_path = output / "routing.sqlite"
    registry = Registry(registry_path)
    notes = ROOT / "contracts/examples/goal_notes_regression.json"
    registry.initialize()
    before = preserve_family_routes(registry, notes)
    registry.transition("activate")
    if preserve_family_routes(registry, notes) != before:
        raise RuntimeError("Un routage extérieur à Tâches a changé.")
    result = {"status": "running", "scope": "disposable", "evolution": "excluded"}
    print("Matrice des décisions Path A et déterministes dans le même bac", flush=True)
    bar = evaluate(runtime, wheel_request, [facts for _, _, facts in CASES], output)
    comparison = [{"id": name, "expected": expected, "signals": facts, **observed}
                  for (name, expected, facts), observed in zip(CASES, bar["decisions"], strict=True)]
    result["decisions"] = {**bar, "decisions": comparison,
                           "scores": {arm: summary(comparison, arm) for arm in ("deterministic", "akasha_model")}}
    write_report(output, result)
    print(json.dumps(result["decisions"]["scores"]), flush=True)

    # Rejeu d'une preuve réservée déjà connue. Le graphe et la consigne sont identiques dans les deux bras.
    case = json.loads((FIXTURES / "cases.json").read_bytes())["cases"][0]
    folder = output / "case"
    prepare(case, folder)
    contract = output / "coverage.json"
    plan = output / "plan.json"
    plan.write_text(json.dumps(case["coverage"], ensure_ascii=False), encoding="utf-8")
    module = "akasha_brain.tasks_routing"
    cli(module, "bind", "--case", folder, "--plan", plan, "--target", case["target"], "--output", contract)
    options = ("--registry", registry_path, "--case", folder, "--coverage", contract, "--runtime", runtime, "--rbitnet", *paths)
    result["tasks"] = {}
    seen = {bar["sandbox_id"]}
    for label, extra in (("deterministic", ()), ("akasha_model", ("--gate-request", wheel_request))):
        print(f"Tâches {label}, même consigne et même contrat", flush=True)
        started = perf_counter()
        observed = cli(module, "run", *options, "--output", output / label, *extra)
        total = round(perf_counter() - started, 3)
        checks = observed["trace"][-1]["result"]
        if (observed["route"]["graph"] != SPECIALIST or observed["accepted_attempt"] != 1
                or not all(checks["filters"].values()) or not checks["sqlite_unchanged"]
                or not observed["sandbox_stopped"] or observed["sandbox_id"] in seen
                or observed["evolution"] != "excluded"):
            raise RuntimeError(f"Le rejeu Tâches {label} a divergé.")
        seen.add(observed["sandbox_id"])
        result["tasks"][label] = {
            "route": observed["route"], "filters": checks["filters"], "sqlite_unchanged": checks["sqlite_unchanged"],
            "sandbox_id": observed["sandbox_id"], "sandbox_stopped": observed["sandbox_stopped"],
            "accepted_attempt": observed["accepted_attempt"], "graph_s": observed["wall_s"], "total_s": total,
        }
        if label == "akasha_model":
            gate = observed["gate"]
            if (gate["effective"] != "ready" or gate["decisions"][0]["akasha_model"] != "ready"
                    or not gate["sandbox_stopped"] or gate["sandbox_id"] in seen):
                raise RuntimeError("La décision Path A intégrée n'est pas attestée.")
            seen.add(gate["sandbox_id"])
            result["tasks"][label]["gate"] = gate
        write_report(output, result)
    no_gate, with_gate = (result["tasks"][label] for label in ("deterministic", "akasha_model"))
    result["task_total_delta_s"] = round(with_gate["total_s"] - no_gate["total_s"], 3)

    print("Non-régression Notes code et bureau", flush=True)
    for label in ("notes", "notes-recheck"):
        desktop = cli("akasha_brain", "run", notes, "--rapidocr", "--first-diff-seed", 742,
                      "--python-runtime", runtime, "--output", output / label, "--rbitnet", *paths, exit_codes=(0, 1))
        if evidence(desktop, desktop=True)["verified"]:
            break
        last = desktop.get("trace", [])[-1:]
        if not desktop.get("sandbox_stopped") or not last or last[0]["id"] != "verify_desktop":
            break
        result["notes_first_failure"] = {"sandbox_id": desktop["sandbox_id"], "error": desktop["error"],
                                         "total_s": desktop["wall_s"]}
        write_report(output, result)
    if not evidence(desktop, desktop=True)["verified"] or desktop["sandbox_id"] in seen:
        raise RuntimeError("La non-régression Notes n'est pas confirmée.")
    seen.add(desktop["sandbox_id"])
    steps = {step["id"]: step["result"] for step in desktop["trace"]}
    result["notes"] = {"sandbox_id": desktop["sandbox_id"], "sandbox_stopped": True, "total_s": desktop["wall_s"],
                       "tests": steps["verify"]["passed"], "sqlite_exit": steps["verify"]["sqlite_verifier_exit"],
                       "desktop": steps["verify_desktop"]["desktop"]}

    print("Non-régression projet jetable", flush=True)
    project = project_check(runtime, output)
    if project["validation"]["sandbox_id"] in seen or preserve_family_routes(registry, notes) != before:
        raise RuntimeError("Un contrôle de non-régression a divergé.")
    seen.add(project["validation"]["sandbox_id"])
    events = verify_chain(registry_path)
    if events.count("gate_evaluated") != 1 or events[-1] != "gate_evaluated":
        raise RuntimeError("La décision intégrée manque au journal.")
    result.update(status="passed", project=project, other_family_routes=before, registry_events=events,
                  distinct_sandboxes=len(seen))
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--gate-request", type=Path, required=True)
    parser.add_argument("--rbitnet", type=Path, nargs=3, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.runtime.resolve(strict=True), args.gate_request.resolve(strict=True),
                 [path.resolve(strict=True) for path in args.rbitnet], args.output.resolve())
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
