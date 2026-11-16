"""Vérifier la version active et soumettre l'objectif au compilateur figé."""

import json
from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "frozen"))
    from akasha_brain.planning import PlanningError, compile_goal, load_catalog
    from contracts.akasha_contracts.errors import ErrorCode
    from contracts.akasha_contracts.validate import validate

    nominal = json.loads((root / "frozen/contracts/examples/goal_notes_regression.json").read_text(encoding="utf-8"))
    frozen = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    goal = json.loads((root / "goal.json").read_text(encoding="utf-8"))
    catalog = load_catalog()
    if compile_goal(nominal, catalog, rbitnet=True) != frozen or validate(goal, "GoalSpec"):
        return 0x4900
    try:
        compile_goal(goal, catalog, rbitnet=True)
    except PlanningError as error:
        return 0x4901 if error.error.code == ErrorCode.CAPABILITY_UNAVAILABLE else 0x4903
    return 0x4902


if __name__ == "__main__":
    raise SystemExit(main())
