"""Qualifie les refus avant suppression sur des projets jetables dans Windows Sandbox."""

import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from time import perf_counter
from uuid import UUID, uuid4
from zipfile import ZipFile

from akasha_brain.notes_sandbox import POWERSHELL, active_sandboxes, guest_exit, read_profile, wait_for_guest
from bench.harness.check_project_transition import CASES, FLAGS, OUTCOMES, PACKET
from bench.run_guided_repair import BENCH, file_hash, write_report, wsb
from bench.run_tasks_transfer import PACKAGES

REPO = BENCH.parent
HARNESS = ("check_project_transition.py", "probe_notes_isolation.ps1", "probe_guest_channels.ps1")


def stage_input(output: Path, runtime: Path, tag: str) -> tuple[Path, dict]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True, timeout=10).strip()
    stage = output / "input"
    stage.mkdir()
    source = output / "source.zip"
    subprocess.run(["git", "archive", "--format=zip", f"--output={source}", commit,
                    "akasha_brain", "contracts/akasha_contracts", "contracts/schemas", "bench/run_guided_repair.py"],
                   cwd=REPO, check=True, timeout=20)
    with ZipFile(source) as archive:
        archive.extractall(stage)
    shutil.copytree(runtime, stage / "python")
    site = Path(sys.prefix) / "Lib" / "site-packages"
    guest_site = stage / "python" / "Lib" / "site-packages"
    guest_site.mkdir(parents=True, exist_ok=True)
    for name in PACKAGES:
        shutil.copytree(site / name, guest_site / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(site / "typing_extensions.py", guest_site / "typing_extensions.py")
    for name in HARNESS:
        shutil.copyfile(BENCH / "harness" / name, stage / name)
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    return stage, {
        "commit": commit,
        "source_archive_sha256": file_hash(source),
        "test_sha256": file_hash(stage / HARNESS[0]),
        "guard_sha256": file_hash(stage / "akasha_brain/project_transition.py"),
        "apply_sha256": file_hash(stage / "akasha_brain/project.py"),
        "python_sha256": file_hash(stage / "python/python.exe"),
    }


def decode_case(packet: int, expected_outcome: int, expected_handles: int) -> dict:
    if packet & ~0xFF3F != PACKET:
        raise RuntimeError(f"Exécution invitée interrompue ({packet:#x}).")
    outcome_id = (packet >> 8) & 0xFF
    outcome = None
    if outcome_id < len(OUTCOMES):
        outcome = dict(zip(("code", "reason", "guard", "risk_class"), OUTCOMES[outcome_id], strict=True))
    checks = {name: bool(packet & (1 << bit)) for bit, name in enumerate(FLAGS)}
    return {
        "verdict": outcome,
        "expected_outcome": OUTCOMES[expected_outcome][0],
        "native_handle_attempts": expected_handles if checks["expected_native_handle_attempts"] else None,
        "native_delete_calls": int(expected_outcome == 0) if checks["expected_native_delete_calls"] else None,
        "checks": checks,
        "status": "passed" if outcome_id == expected_outcome and all(checks.values()) else "failed",
    }


def run(runtime: Path, output: Path) -> dict:
    if active_sandboxes():
        raise RuntimeError("Un autre Windows Sandbox est actif.")
    began = perf_counter()
    profile = read_profile()
    tag, sandbox = secrets.token_hex(4), str(uuid4())
    mount = fr"C:\AkashaGuidedInput-{tag}"
    output.mkdir(parents=True)
    stage, sources = stage_input(output, runtime, tag)
    report = {"protocol": "phase5-project-transition-guard-v1", "status": "running",
              "sandbox_id": sandbox, "sources": sources, "cases": {}}
    write_report(output, report)
    try:
        if str(UUID(wsb("start", "--id", sandbox, "--config", profile)["Id"])) != sandbox:
            raise RuntimeError("Identité inattendue pour le bac.")
        wait_for_guest(sandbox)
        if active_sandboxes() != [sandbox]:
            raise RuntimeError("Le bac doit être l'unique session active.")
        wsb("share", "--id", sandbox, "--host-path", str(stage), "--sandbox-path", mount)
        isolation = guest_exit(sandbox, fr"{POWERSHELL} -File {mount}\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox, fr"{POWERSHELL} -File {mount}\probe_guest_channels.ps1")
        report["isolation"] = {"mount_and_scratch_exit": isolation, "channels_exit": channels}
        if isolation != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError("Confinement du bac non attesté.")

        for case, (expected_outcome, expected_handles) in CASES.items():
            start = perf_counter()
            packet = guest_exit(sandbox, fr"{mount}\python\python.exe -E -s -B -X utf8 "
                                fr"{mount}\check_project_transition.py {case}")
            if packet & ~0xFF3F == PACKET:
                row = decode_case(packet, expected_outcome, expected_handles)
            else:
                row = {"status": "error", "guest_exit_code": packet}
            report["cases"][case] = {**row, "wall_s": round(perf_counter() - start, 3)}
            write_report(output, report)
            print(f"{case}: {row['status']}, code invité {packet:#x}", flush=True)

        rejected = [row for name, row in report["cases"].items() if CASES[name][0] != 0]
        report["summary"] = {
            "invalid_cases": len(rejected),
            "blocked_before_delete": sum(row["status"] == "passed" for row in rejected),
            "invalid_native_delete_calls": sum(row.get("native_delete_calls") or 0 for row in rejected)
                if all(row.get("native_delete_calls") is not None for row in rejected) else None,
            "approved_control_applied": report["cases"]["approved_unchanged"]["status"] == "passed",
        }
        if not all(row["status"] == "passed" for row in report["cases"].values()):
            raise RuntimeError("Écart dans la qualification de la garde.")
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        try:
            if sandbox in active_sandboxes():
                wsb("stop", "--id", sandbox)
            report["sandbox_stopped"] = sandbox not in active_sandboxes()
        finally:
            report["wall_s"] = round(perf_counter() - began, 3)
            write_report(output, report)
    if not report["sandbox_stopped"]:
        raise RuntimeError("L'arrêt du bac n'est pas confirmé.")
    report["status"] = "passed"
    write_report(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.runtime.resolve(strict=True), args.output.resolve())
    print(json.dumps({"summary": report["summary"], "wall_s": report["wall_s"]}), flush=True)


if __name__ == "__main__":
    main()
