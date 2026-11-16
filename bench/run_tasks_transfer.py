"""Évaluer la variante réservée Tâches dans Windows Sandbox."""

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from time import perf_counter
from uuid import UUID, uuid4
from zipfile import ZipFile

from akasha_brain.notes_sandbox import (
    CHANNELS, POWERSHELL, active_sandboxes, guest_exit, read_profile, require_step_permission, wait_for_guest,
)
from akasha_brain.planning import PlanningError
from bench.run_guided_repair import BENCH, file_hash, write_report, wsb

FIXTURE = BENCH / "tasks_transfer_v2"
FROZEN_FILES = (
    "akasha_brain/__init__.py", "akasha_brain/planning.py", "akasha_brain/capabilities.json",
    "contracts/akasha_contracts", "contracts/schemas", "contracts/examples/goal_notes_regression.json",
)
PACKAGES = ("attr", "attrs", "jsonschema", "jsonschema_specifications", "referencing", "rpds")
FILTERS = ("À faire", "Terminées", "Toutes")


def stage_admission(stage: Path, runtime: Path, frozen: dict) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", frozen["commit"]):
        raise RuntimeError("Référence Git non figée.")
    archive = stage.parent / "frozen.zip"
    subprocess.run(["git", "archive", "--format=zip", f"--output={archive}", frozen["commit"], *FROZEN_FILES],
                   cwd=BENCH.parent, check=True, timeout=15)
    with ZipFile(archive) as bundle:
        bundle.extractall(stage / "frozen")
    (stage / "plan.json").write_text(json.dumps(frozen["plan"]), encoding="utf-8")
    shutil.copytree(runtime, stage / "python")
    site = Path(sys.prefix) / "Lib" / "site-packages"
    for name in PACKAGES:
        shutil.copytree(site / name, stage / "packages" / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(site / "typing_extensions.py", stage / "packages" / "typing_extensions.py")
    distributions = ("attrs", "jsonschema", "jsonschema-specifications", "referencing", "rpds-py", "typing-extensions")
    return {name: version(name) for name in distributions}


def shared_input(sandbox: str, folder: Path, tag: str) -> str:
    guest = fr"C:\AkashaGuidedInput-{tag}"
    wsb("share", "--id", sandbox, "--host-path", str(folder), "--sandbox-path", guest)
    result = guest_exit(sandbox, f"{POWERSHELL} -File {guest}\\probe_notes_isolation.ps1 -Tag {tag}")
    if result != 0x450F:
        raise RuntimeError(f"Montage de transfert en lecture seule non attesté ({result}).")
    return guest


def decode_filters(code: int, seed: list) -> dict:
    if code & ~0x3FF != 0x59000000:
        raise RuntimeError(f"Contrôle de l'interface Tâches interrompu ({code}).")
    expected = ([title for _, title, closed in seed if closed == 0],
                [title for _, title, closed in seed if closed == 1],
                [title for _, title, _ in seed])
    filters = {}
    for index, name in enumerate(FILTERS):
        mask = (code >> (index * 3)) & 7
        observed = [title for offset, (_, title, _) in enumerate(seed) if mask & (1 << offset)]
        filters[name] = {
            "expected": expected[index], "observed": observed,
            "passed": not bool(mask & 4) and observed == expected[index],
            "unexpected_rows_or_order": bool(mask & 4),
        }
    return {"filters": filters, "sqlite_unchanged": bool(code & 0x200), "guest_exit_code": code}


def run_transfer(runtime: Path, registry: Path, lock: Path, out: Path) -> dict:
    out.mkdir(parents=True)
    wall = perf_counter()
    sandbox = None
    registry_digest = None
    report = {"status": "running", "scenario": "tasks-transfer-v2", "evolution": "excluded"}
    try:
        frozen = json.loads(lock.read_text(encoding="utf-8"))
        registry_digest = file_hash(registry)
        if registry_digest != frozen["registry_sha256"] or frozen["plan"]["graph_id"] != "notes-rbitnet":
            raise RuntimeError("Le registre actif diffère de l'état figé pour cette mesure.")
        report["frozen_graph"] = frozen["plan"]
        report["source_commit"] = frozen["commit"]
        report["freeze_sha256"] = file_hash(lock)
        if active_sandboxes():
            raise RuntimeError("Une session Windows Sandbox est déjà active.")
        profile = read_profile()
        admission_tag, witness_tag = secrets.token_hex(4), secrets.token_hex(4)
        admission = out / "admission"
        witness = out / "witness"
        report["compiler_dependencies"] = stage_admission(admission, runtime, frozen)
        witness.mkdir()
        for folder, tag, scripts in (
            (admission, admission_tag, ("admit.py", "goal.json")),
            (witness, witness_tag, ("control.py", "board.py", "state.json")),
        ):
            for name in (*scripts, "run_guest.ps1"):
                shutil.copyfile(FIXTURE / name, folder / name)
            shutil.copyfile(BENCH / "harness/probe_notes_isolation.ps1", folder / "probe_notes_isolation.ps1")
            (folder / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        shutil.copyfile(BENCH / "harness/probe_guest_channels.ps1", admission / "probe_guest_channels.ps1")
        report["fixture_sha256"] = {path.name: file_hash(path) for path in sorted(FIXTURE.iterdir()) if path.is_file()}
        goal = json.loads((admission / "goal.json").read_text(encoding="utf-8"))
        seed = json.loads((witness / "state.json").read_text(encoding="utf-8"))

        sandbox = str(uuid4())
        report["sandbox_id"] = sandbox
        if str(UUID(wsb("start", "--id", sandbox, "--config", profile)["Id"])) != sandbox:
            raise RuntimeError("Identifiant du bac inattendu.")
        wait_for_guest(sandbox)
        entry = shared_input(sandbox, admission, admission_tag)
        code = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\probe_guest_channels.ps1")
        if code not in (0x410F, 0x411F):
            raise RuntimeError(f"Canaux du bac non attestés ({code}).")
        report["isolation"] = {"declared_disabled_channels": CHANNELS, "admission_read_only": True, "probe": code}
        require_step_permission({"id": "transfer-admission", "action": "observe"}, goal, active_sandboxes() == [sandbox])
        code = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\run_guest.ps1 -Tag {admission_tag} -Phase admit")
        if code != 0x4901:
            raise RuntimeError(f"Résultat d'admission inattendu pour le graphe figé ({code}).")
        report["transfer"] = {
            "status": "failed", "frozen_plan_recompiled": True, "goal_schema_valid": True,
            "code": "capability_unavailable", "steps_executed": 0, "rbitnet_invoked": False, "guest_exit_code": code,
        }

        entry = shared_input(sandbox, witness, witness_tag)
        report["isolation"]["witness_read_only"] = True
        for phase in ("faulty", "reference"):
            require_step_permission({"id": phase, "action": "test"}, goal, active_sandboxes() == [sandbox])
            code = guest_exit(sandbox, f"{POWERSHELL} -File {entry}\\run_guest.ps1 -Tag {admission_tag} -Phase {phase}")
            report[phase] = decode_filters(code, seed)
        if ([item["passed"] for item in report["faulty"]["filters"].values()] != [False, True, True]
                or not all(item["passed"] for item in report["reference"]["filters"].values())
                or not report["faulty"]["sqlite_unchanged"] or not report["reference"]["sqlite_unchanged"]):
            raise RuntimeError("Le témoin ou le contrôle de non-modification SQLite ne valide pas la variante.")
        report["status"] = "measured"
    except (OSError, RuntimeError, ValueError, KeyError, PlanningError, subprocess.SubprocessError) as error:
        report.update(status="error", error=str(error))
    finally:
        if sandbox:
            try:
                if sandbox in active_sandboxes():
                    wsb("stop", "--id", sandbox)
                report["sandbox_stopped"] = sandbox not in active_sandboxes()
                if not report["sandbox_stopped"]:
                    raise RuntimeError("Arrêt du bac non confirmé.")
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
                report.update(status="error", cleanup_error=str(error))
        report["evolution_registry_unchanged"] = registry_digest is not None and registry.is_file() and (
            file_hash(registry) == registry_digest
        )
        if report["status"] == "measured" and not report["evolution_registry_unchanged"]:
            report.update(status="error", error="Le registre d'évolution a changé.")
        report["wall_s"] = round(perf_counter() - wall, 3)
        write_report(out, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python-runtime", "registry", "freeze", "output"):
        parser.add_argument(f"--{name}", type=lambda value: Path(value).resolve(), required=True)
    args = parser.parse_args()
    report = run_transfer(args.python_runtime, args.registry, args.freeze, args.output)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
