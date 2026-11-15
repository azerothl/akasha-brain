"""Point d'entrée du parcours Notes de la phase 1."""

import argparse
import json
from pathlib import Path

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .notes_desktop import run_desktop
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
    run_parser = subcommands.add_parser("run", help="Exécuter le graphe Notes dans un bac dédié")
    run_parser.add_argument("goal", type=Path, help="Fichier JSON GoalSpec")
    run_parser.add_argument("--python-runtime", required=True, type=Path, help="Python portable du banc")
    run_parser.add_argument("--output", required=True, type=Path, help="Nouveau dossier de rapport")
    run_parser.add_argument("--rbitnet", nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"),
                            help="Utiliser les artefacts Rbitnet CPU du protocole évalué")
    run_parser.add_argument("--first-diff-seed", type=int,
                            help="Évaluer le premier diff Rbitnet avec cette graine")
    desktop = subcommands.add_parser("run-desktop", help="Vérifier Notes avec RapidOCR dans le bac")
    desktop.add_argument("goal", type=Path, help="Fichier JSON GoalSpec")
    desktop.add_argument("--python-runtime", required=True, type=Path, help="Python portable du banc")
    desktop.add_argument("--output", required=True, type=Path, help="Nouveau dossier de rapport")
    desktop.add_argument("--diff", required=True, type=Path, help="Diff Rbitnet Notes validé")
    args = cli.parse_args()
    if args.command == "run" and args.first_diff_seed is not None:
        if not args.rbitnet or args.first_diff_seed < 0:
            run_parser.error("--first-diff-seed exige Rbitnet et une graine positive ou nulle")

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
        else:
            goal = json.loads(args.goal.read_text(encoding="utf-8-sig"))
            if args.command == "run":
                engine = RbitnetPaths(*(path.resolve() for path in args.rbitnet)) if args.rbitnet else None
                result = run_notes(goal, catalog, args.python_runtime.resolve(), args.output.resolve(), engine,
                                   first_diff_seed=args.first_diff_seed)
            elif args.command == "run-desktop":
                result = run_desktop(goal, catalog, args.python_runtime.resolve(), args.output.resolve(), args.diff.resolve())
            else:
                result = compile_goal(goal, catalog, rbitnet=args.rbitnet)
    except (OSError, UnicodeError, json.JSONDecodeError):
        error = AkashaError(ErrorCode.CONTRACT_SCHEMA_VIOLATION, "Impossible de lire le JSON d'entrée.")
        print(json.dumps({"error": error.as_dict()}, ensure_ascii=True, indent=2))
        return 1
    except PlanningError as exc:
        print(json.dumps({"error": exc.error.as_dict()}, ensure_ascii=True, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if args.command in {"run", "run-desktop"} and result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
