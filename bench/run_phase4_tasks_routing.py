"""Vérifie l'admission et le retrait Tâches sur des registres et projets jetables."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from akasha_brain.notes_evolution import evidence
from akasha_brain.planning import compile_goal, load_catalog
from akasha_brain.tasks_routing import REFERENCE, SPECIALIST, Registry
from bench.communication.templates import render_template
from bench.run_guided_repair import BENCH, write_report
from bench.run_notes_link_promotion import verify_chain
from bench.run_phase4_tasks_reserved import FIXTURES, ROOT, prepare
from bench.run_phase4_tasks_specialist import measure_pair


def cli(module: str, command: str, *arguments, exit_codes: tuple[int, ...] = (0,)) -> dict:
    process = subprocess.run([sys.executable, "-X", "utf8", "-B", "-m", module, command, *map(str, arguments)],
                             capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode not in exit_codes:
        raise RuntimeError(f"{module} {command} ({process.returncode})\n{process.stdout}\n{process.stderr}")
    return json.loads(process.stdout)


def preserve_family_routes(registry: Registry, notes: Path) -> dict:
    goal = json.loads(notes.read_bytes())
    catalog = load_catalog()
    compiled = [compile_goal(goal, catalog, rbitnet=repair, rapidocr=ocr)
                for repair, ocr in ((False, False), (True, False), (True, True))]
    cases = json.loads((BENCH / "communication/cases-fr-validation-v1.json").read_bytes())["cases"]
    rendered = {key: render_template(case["fiche"]) for key, case in cases.items()}
    scopes = {"notes": goal, "project": {"inputs": ["project://disposable"]},
              "communication": {"inputs": ["bench://communication"]}}
    excluded = {name: registry.admit(spec, notes.parent, None)["reason"] for name, spec in scopes.items()}
    if (set(excluded.values()) != {"outside_tasks"} or set(key for key, value in rendered.items() if value) != {
            "clarification", "ordre"}):
        raise RuntimeError("Un parcours extérieur a changé de routage.")
    return {"notes_graphs": [plan["graph_id"] for plan in compiled],
            "notes_plans_sha256": sha256(json.dumps(compiled, sort_keys=True).encode()).hexdigest(),
            "communication_templates": rendered, "excluded": excluded}


def project_check(runtime: Path, output: Path) -> dict:
    project = output / "disposable-project"
    project.mkdir()
    source = project / "value.py"
    source.write_text("VALUE = 1\n", encoding="ascii")
    previous = source.read_bytes()
    (project / "check.py").write_text("from value import VALUE\nassert VALUE == 2\n", encoding="ascii")
    replacement = output / "replacement.py"
    replacement.write_text("VALUE = 2\n", encoding="ascii")
    proposal = output / "project-proposal"
    prepared = cli("akasha_brain.project", "prepare", "--project", project, "--output", proposal, "--file", "value.py",
                   "--replacement", replacement, "--test", "check.py", "--python-runtime", runtime)
    refused = cli("akasha_brain.project", "apply", "--project", project, "--proposal", proposal, exit_codes=(1,))
    if (prepared["status"] != "awaiting_approval" or refused["error"]["code"] != "approval_required"
            or source.read_bytes() != previous or not prepared["validation"]["sandbox_stopped"]):
        raise RuntimeError("Le parcours projet n'a pas préservé sa validation et son approbation.")
    applied = cli("akasha_brain.project", "apply", "--project", project, "--proposal", proposal,
                  "--approve", prepared["approval_sha256"])
    if applied["status"] != "applied" or source.read_bytes() != replacement.read_bytes():
        raise RuntimeError("Le diff projet approuvé ne correspond pas au fichier testé.")
    return {"validation": prepared["validation"], "without_approval": refused["error"]["code"], "approved": applied["status"]}


def run(runtime: Path, paths: list[Path], output: Path) -> dict:
    output.mkdir(parents=True)
    registry_path = output / "routing.sqlite"
    registry = Registry(registry_path)
    module = "akasha_brain.tasks_routing"
    # Rejouer la preuve réservée sans ajuster le graphe, la consigne ni l'oracle.
    case = json.loads((FIXTURES / "cases.json").read_bytes())["cases"][0]
    folder = output / "case"
    prepare(case, folder)
    plan = output / "plan.json"
    plan.write_text(json.dumps(case["coverage"], ensure_ascii=False), encoding="utf-8")
    contract = output / "coverage.json"
    cli(module, "bind", "--case", folder, "--plan", plan, "--target", case["target"], "--output", contract)
    notes = ROOT / "contracts/examples/goal_notes_regression.json"
    registry_options = ("--registry", registry_path)
    result = {"status": "running", "scope": "disposable", "case": case["id"], "evolution": "excluded"}
    result["initial"] = cli(module, "init", *registry_options)
    families = preserve_family_routes(registry, notes)
    result["active"] = cli(module, "activate", *registry_options)
    if families != preserve_family_routes(registry, notes):
        raise RuntimeError("L'activation a modifié une autre famille.")
    task_options = (*registry_options, "--case", folder, "--coverage", contract, "--runtime", runtime, "--rbitnet", *paths)
    print("Tâches sous spécialiste actif", flush=True)
    active = cli(module, "run", *task_options, "--output", output / "active")
    result["active_run"] = measure_pair(active, case, {"initial": None, "witness": None}, set())
    result["active_run"].update(route=active["route"])
    if (active["route"]["graph"] != SPECIALIST or active["accepted_attempt"] != 1
            or not result["active_run"]["evaluated"]):
        raise RuntimeError("L’exécution du spécialiste actif n'est pas certifiée.")
    write_report(output, result)

    print("Notes code et bureau, spécialiste Tâches actif", flush=True)
    for label in ("notes", "notes-recheck"):
        desktop = cli("akasha_brain", "run", notes, "--rapidocr", "--first-diff-seed", 742,
                      "--python-runtime", runtime, "--output", output / label, "--rbitnet", *paths,
                      exit_codes=(0, 1))
        if evidence(desktop, desktop=True)["verified"]:
            break
        failed_step = desktop["trace"][-1] if desktop["trace"] else {}
        if not desktop.get("sandbox_stopped") or failed_step.get("id") != "verify_desktop":
            break
        result["notes_first_failure"] = {"sandbox_id": desktop["sandbox_id"], "error": desktop["error"],
                                         "total_s": desktop["wall_s"]}
        write_report(output, result)
    if not evidence(desktop, desktop=True)["verified"]:
        raise RuntimeError("Le parcours indépendant Notes a échoué.")
    last = {step["id"]: step["result"] for step in desktop["trace"]}
    result["notes"] = {"graph": desktop["graph"]["graph_id"], "sandbox_id": desktop["sandbox_id"],
                       "sandbox_stopped": desktop["sandbox_stopped"], "total_s": desktop["wall_s"],
                       "tests": last["verify"]["passed"], "sqlite_exit": last["verify"]["sqlite_verifier_exit"],
                       "desktop": last["verify_desktop"]["desktop"]}
    print("Projet jetable, spécialiste Tâches actif", flush=True)
    result["project"] = project_check(runtime, output)
    write_report(output, result)

    result["deprecated"] = cli(module, "deprecate", *registry_options)
    result["retired"] = cli(module, "retire", *registry_options)
    print("Tâches après retrait, même cas et même contrat", flush=True)
    retired = cli(module, "run", *task_options, "--output", output / "retired", exit_codes=(0, 1))
    observed = measure_pair(retired, case, result["active_run"], {active["sandbox_id"]})
    observed["route"] = retired["route"]
    if (retired["route"] != {"graph": REFERENCE, "reason": "retired", "state": "retired"}
            or not all(observed[key] for key in ("evaluated", "distinct_sandbox", "same_witness_and_initial"))):
        raise RuntimeError("Le nouveau lancement n'a pas repris la référence.")
    if families != preserve_family_routes(registry, notes):
        raise RuntimeError("Le retrait a modifié une autre famille.")
    events = verify_chain(registry_path)
    if events != ["initialized", "activate", "routed", "deprecate", "retire", "routed"]:
        raise RuntimeError("Le journal ne concorde pas avec l'ordre des décisions.")
    result.update(status="passed", retired_run=observed, other_family_routes=families, registry_events=events)
    for key in ("active_run", "retired_run"):
        result[key].pop("same_witness_and_initial", None)
    result["same_witness_and_initial"] = True
    write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", type=Path, nargs=3, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.runtime.resolve(strict=True), [path.resolve(strict=True) for path in args.rbitnet],
                 args.output.resolve())
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
