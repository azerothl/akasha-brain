"""Échéances des copies locales et de leurs dérivés."""

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path

from contracts.akasha_contracts.validate import validate

from .planning import PlanningError

DEFAULT_POLICY = {
    "version": "1.0.0",
    "windows_days": {"minimized_results": 90, "real_contents": 30, "captures": 7},
    "backup": {"daily": True, "retention_days": 7, "includes_real_contents": False},
}


def load_policy() -> dict:
    path = os.environ.get("AKASHA_RETENTION_POLICY")
    if not path:
        return DEFAULT_POLICY
    policy = json.loads(Path(path).read_bytes())
    if errors := validate(policy, "RetentionPolicy"):
        raise PlanningError(errors[0])
    return policy


def deadline(created_at: datetime, kind: str, *, parent_deadlines=(), policy=None) -> datetime:
    policy = load_policy() if policy is None else policy
    days = policy["backup"]["retention_days"] if kind == "backup" else policy["windows_days"][kind]
    return min((created_at + timedelta(days=days), *parent_deadlines))


def copy_deadline(created_at: str, stored_expires_at: str, *, policy=None) -> datetime:
    return deadline(datetime.fromisoformat(created_at), "real_contents",
                    parent_deadlines=(datetime.fromisoformat(stored_expires_at),), policy=policy)


def main() -> None:
    from .experience import prune_experiences
    from .memory_budget import enforce
    from .memory_store import MemoryStore
    from .project_evolution import expire_copies

    parser = argparse.ArgumentParser(description="Purger les expériences et copies d’évolution arrivées à échéance.")
    parser.add_argument("--db", type=Path, required=True, help="Registre local")
    parser.add_argument("--project", type=Path, action="append", default=[], help="Dossier du projet à traiter")
    args = parser.parse_args()
    result = {
        "expired_experiences": prune_experiences(args.db),
        "projects": [{"project": str(project), "erasures": expire_copies(project, args.db)} for project in args.project],
    }
    memory = MemoryStore(args.db)
    if memory.configured():
        result["memory"] = memory.expire()
        if budget := enforce(memory):
            result["memory"]["disk"] = budget
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
