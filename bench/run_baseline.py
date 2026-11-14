"""Baseline fixe : localisation → réparation → validation (banc notes).

Pipeline déterministe, sans modèle : exécute les tests du banc sur une
copie de travail (TEMP, le banc figé n'est jamais modifié), identifie les
tests en échec (localisation), applique la correction de référence scellée
(réparation), puis rejoue tests et vérificateur (validation). Mesure le
temps mur de bout en bout (métrique de coût primaire, spec §15.1).

Usage : .\\.venv\\Scripts\\python.exe bench/run_baseline.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, "..", ".venv", "Scripts", "python.exe")


def run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)


def main() -> int:
    t0 = time.perf_counter()
    work = tempfile.mkdtemp(prefix="akasha-baseline-")
    shutil.copytree(os.path.join(ROOT, "notes"), os.path.join(work, "notes"))
    shutil.copytree(os.path.join(ROOT, "reference"), os.path.join(work, "reference"))

    # 1. Localisation : tests sur la version fautive.
    before = run([PYTHON, "-m", "pytest", "notes", "-q"], cwd=work)
    failing = [line for line in before.stdout.splitlines()
               if line.startswith("FAILED")]
    print(f"[localiser] échec initial : {len(failing)} test(s) en échec")
    for line in failing:
        print(f"  - {line}")

    # 2. Réparation : correction de référence scellée sur la copie de travail.
    shutil.copyfile(os.path.join(work, "reference", "notes_reference_store.py"),
                    os.path.join(work, "notes", "notes_store.py"))

    # 3. Validation : tests + vérificateur indépendant.
    after = run([PYTHON, "-m", "pytest", "notes", "-q"], cwd=work)
    print(f"[valider] tests après réparation : {after.stdout.strip().splitlines()[-1]}")
    verifier = run(
        [PYTHON, os.path.join("notes", "verifiers", "verify_notes.py"),
         "--db", os.path.join(work, "notes_check.db"), "--reset"], cwd=work)
    print(f"[valider] vérificateur : {verifier.stdout.strip()}")

    wall = time.perf_counter() - t0
    print(f"[coût] temps mur de bout en bout : {wall:.1f} s")
    ok = after.returncode == 0 and verifier.returncode == 0 and len(failing) > 0
    print("BASELINE " + ("PASS" if ok else "FAIL"))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
