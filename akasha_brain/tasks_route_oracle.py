"""Contrôle dans le bac que le filtre localisé correspond au contrat admis."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from tasks_oracle_deltas import decode_oracle


def main() -> int:
    result = subprocess.run([sys.executable, "-B", str(ROOT / "independent_oracle.py"), *sys.argv[1:]],
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
    if sys.argv[1] == "localize":
        observed = decode_oracle(result.returncode)
        failed = [name for name, valid in observed["filters"].items() if not valid]
        target = json.loads((ROOT / "routing_target.json").read_bytes())
        if failed != [target]:
            return 63
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
