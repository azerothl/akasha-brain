"""Point d'entrée du parcours Notes de la phase 1."""

import argparse
import json
from pathlib import Path
import sqlite3

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .notes_desktop import run_desktop
from .notes_evolution import EvolutionBudget, evolution_status, rollback, run_managed
from .notes_repair import RbitnetPaths
from .notes_runtime import run_notes
from .planning import PlanningError, compile_goal, load_catalog


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    subcommands = cli.add_subparsers(dest="command", required=True)
    subcommands.add_parser("capabilities", help="Lister le registre des capacités")
    compile_parser = subcommands.add_parser("compile", help="Compiler un objectif du banc")
    compile_parser.add_argument("goal", type=Path, help="Fichier JSON GoalSpec")
    compile_parser.add_argument("--rbitnet", action="store_true", help="Sélectionner la réparation Rbitnet CPU")
    compile_parser.add_argument("--rapidocr", action="store_true", help="Ajouter la vérification bureau après les tests")
    run_parser = subcommands.add_parser("run", help="Exécuter le graphe Notes dans un bac dédié")
    run_parser.add_argument("goal", type=Path, help="Fichier JSON GoalSpec")
    run_parser.add_argument("--python-runtime", required=True, type=Path, help="Python portable du banc")
    run_parser.add_argument("--output", required=True, type=Path, help="Nouveau dossier de rapport")
    run_parser.add_argument("--rbitnet", nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"),
                            help="Utiliser les artefacts Rbitnet CPU du protocole évalué")
    run_parser.add_argument("--first-diff-seed", type=int,
                            help="Évaluer le premier diff Rbitnet avec cette graine")
    run_parser.add_argument("--rapidocr", action="store_true", help="Vérifier le bureau avec RapidOCR v2 après les tests")
    run_parser.add_argument("--evolution-db", type=Path, help="Sélectionner le graphe actif et activer l'évolution Notes")
    run_parser.add_argument("--evolution-wall-s", type=int, default=420, help="Durée autorisée pour les essais candidats")
    run_parser.add_argument("--evolution-max-trials", type=int, default=3, help="Nombre maximal d'essais candidats")
    run_parser.add_argument("--evolution-cpu-threads", type=int, default=8, help="Taille des pools CPU Rbitnet")
    run_parser.add_argument("--evolution-model-ram-mb", type=int, default=8192, help="Budget d'admission Rbitnet en Mio")
    evolution = subcommands.add_parser("evolution", help="Consulter ou restaurer le graphe actif du banc Notes")
    evolution.add_argument("action", choices=("status", "rollback"))
    evolution.add_argument("--db", required=True, type=Path)
    desktop = subcommands.add_parser("run-desktop", help="Vérifier Notes avec RapidOCR dans le bac")
    desktop.add_argument("goal", type=Path, help="Fichier JSON GoalSpec")
    desktop.add_argument("--python-runtime", required=True, type=Path, help="Python portable du banc")
    desktop.add_argument("--output", required=True, type=Path, help="Nouveau dossier de rapport")
    desktop.add_argument("--diff", required=True, type=Path, help="Diff Rbitnet Notes validé")
    args = cli.parse_args()
    if args.command == "run" and args.first_diff_seed is not None:
        if not args.rbitnet or args.first_diff_seed < 0:
            run_parser.error("--first-diff-seed exige Rbitnet et une graine positive ou nulle")
    if args.command == "run" and args.evolution_db:
        if not args.rbitnet or args.rapidocr or args.first_diff_seed is not None:
            run_parser.error("--evolution-db exige Rbitnet et sélectionne le graphe actif avec la graine 742")
        if min(args.evolution_wall_s, args.evolution_max_trials) < 0:
            run_parser.error("les budgets de temps et d'essais doivent être positifs ou nuls")
        if min(args.evolution_cpu_threads, args.evolution_model_ram_mb) <= 0:
            run_parser.error("les budgets CPU et RAM doivent être strictement positifs")

    try:
        catalog = load_catalog()
        if args.command == "capabilities":
            result = [
                {
                    "capability_id": capability_id,
                    "version": version,
                    "status": "evaluated" if "evaluation" in entry else "announced",
                    "evaluation": entry.get("evaluation"),
                }
                for (capability_id, version), entry in catalog.items()
            ]
        elif args.command == "evolution":
            path = args.db.resolve()
            if not path.is_file():
                raise PlanningError(AkashaError(
                    ErrorCode.CONTRACT_PRECONDITION_FAILED, "Journal d'évolution introuvable.",
                ))
            result = evolution_status(path) if args.action == "status" else rollback(path)
        else:
            goal = json.loads(args.goal.read_text(encoding="utf-8-sig"))
            if args.command == "run":
                engine = RbitnetPaths(*(path.resolve() for path in args.rbitnet)) if args.rbitnet else None
                runtime, output = args.python_runtime.resolve(), args.output.resolve()
                if args.evolution_db:
                    budget = EvolutionBudget(args.evolution_wall_s, args.evolution_max_trials,
                                             args.evolution_cpu_threads, args.evolution_model_ram_mb)
                    result = run_managed(goal, catalog, runtime, output, engine, args.evolution_db.resolve(), budget)
                else:
                    result = run_notes(goal, catalog, runtime, output, engine,
                                       first_diff_seed=args.first_diff_seed, rapidocr=args.rapidocr)
            elif args.command == "run-desktop":
                result = run_desktop(goal, catalog, args.python_runtime.resolve(), args.output.resolve(), args.diff.resolve())
            else:
                result = compile_goal(goal, catalog, rbitnet=args.rbitnet, rapidocr=args.rapidocr)
    except (OSError, UnicodeError, json.JSONDecodeError):
        error = AkashaError(ErrorCode.CONTRACT_SCHEMA_VIOLATION, "Impossible de lire le JSON d'entrée.")
        print(json.dumps({"error": error.as_dict()}, ensure_ascii=True, indent=2))
        return 1
    except PlanningError as exc:
        print(json.dumps({"error": exc.error.as_dict()}, ensure_ascii=True, indent=2))
        return 1
    except (RuntimeError, sqlite3.Error) as exc:
        error = AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(exc))
        print(json.dumps({"error": error.as_dict()}, ensure_ascii=True, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if args.command in {"run", "run-desktop"} and result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
