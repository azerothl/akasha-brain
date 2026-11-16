"""Capture trois états de Notes autour d'une sauvegarde et d'une relance."""

import argparse
import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from akasha_brain.desktop_state import NOTES_WINDOW_TITLE, decode_notes_observation
from akasha_brain.notes_sandbox import POWERSHELL, active_sandboxes, guest_exit, read_profile, wait_for_guest
from bench.run_guided_repair import BENCH, file_hash, write_report, wsb

INPUTS = {
    "notes_app.py": "notes/notes_app.py",
    "notes_store.py": "reference/notes_reference_store.py",
    **{name: f"harness/{name}" for name in (
        "observe_notes_desktop.ps1", "observe_notes_desktop.py",
        "probe_notes_isolation.ps1", "probe_guest_channels.ps1",
    )},
}
PHASES = ("before_save", "after_save", "after_restart")


def check_states(states: dict) -> dict:
    pids = [states[phase]["process"]["pid"] for phase in PHASES]
    expected_window = {
        "title": NOTES_WINDOW_TITLE,
        "visible": True,
        "foreground_owned_by_process": True,
        "uia_focus_owned_by_process": True,
    }
    return {
        "notes_process_alive_each_time": all(state["process"]["alive"] for state in states.values()),
        "window_visible_and_focused_each_time": all(state["window"] == expected_window for state in states.values()),
        "same_process_after_save": pids[0] == pids[1],
        "different_process_after_restart": pids[1] != pids[2],
        "independent_sqlite_empty_then_exact_fixture_twice": [
            states[phase]["sqlite"]["row_count"] for phase in PHASES
        ] == [0, 1, 1],
    }


def run(runtime: Path, output: Path) -> dict:
    begin = perf_counter()
    profile = read_profile()
    if active_sandboxes():
        raise RuntimeError("Une autre session Windows Sandbox est ouverte.")
    output.mkdir(parents=True)
    stage = output / "input"
    stage.mkdir()
    shutil.copytree(runtime, stage / "python")
    for name, source in INPUTS.items():
        shutil.copyfile(BENCH / source, stage / name)
    hashes = {name: file_hash(stage / name) for name in INPUTS}
    tag, sandbox_id = secrets.token_hex(4), str(uuid4())
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    guest = fr"C:\AkashaGuidedInput-{tag}"
    probe = fr"{POWERSHELL} -File {guest}\observe_notes_desktop.ps1 -Tag {tag}"
    report = {
        "protocol": "phase5-notes-desktop-state-v1",
        "status": "running",
        "scope": "synthetic_notes_reference",
        "save_action": "fixed synthetic fixture through the Notes Tk save button",
        "inputs_sha256": hashes,
        "sandbox_id": sandbox_id,
        "observations": {},
    }
    write_report(output, report)
    try:
        if str(UUID(wsb("start", "--id", sandbox_id, "--config", profile)["Id"])) != sandbox_id:
            raise RuntimeError("Identité inattendue pour le bac.")
        wait_for_guest(sandbox_id)
        if active_sandboxes() != [sandbox_id]:
            raise RuntimeError("Le bac Notes doit être l'unique session active.")
        wsb("share", "--id", sandbox_id, "--host-path", str(stage), "--sandbox-path", guest)
        isolation = guest_exit(sandbox_id, fr"{POWERSHELL} -File {guest}\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox_id, fr"{POWERSHELL} -File {guest}\probe_guest_channels.ps1")
        report["isolation"] = {"mount_and_scratch_exit": isolation, "channels_exit": channels}
        if isolation != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError("Les sondes d'isolation de Notes ont échoué.")
        print("Bac neuf prêt, montage en lecture seule et canaux contrôlés.", flush=True)

        started_at = datetime.now(UTC).isoformat()
        capture_begin = perf_counter()
        capture_exit = guest_exit(sandbox_id, probe)
        finished_at = datetime.now(UTC).isoformat()
        report.update(capture_exit=capture_exit, capture_wall_s=round(perf_counter() - capture_begin, 3))
        if capture_exit != 0x4600:
            raise RuntimeError(f"La capture des états Notes a échoué ({capture_exit:#x}).")
        for phase in PHASES:
            packet = guest_exit(sandbox_id, f"{probe} -Mode {phase}")
            state = decode_notes_observation(packet, started_at=started_at, finished_at=finished_at)
            report["observations"][phase] = state
            print(f"{phase}: PID {state['process']['pid']}, SQLite {state['sqlite']['row_count']} ligne(s)", flush=True)
        checks = check_states(report["observations"])
        checks["staged_sources_unchanged"] = all(file_hash(stage / name) == digest for name, digest in hashes.items())
        report["checks"] = checks
        if not all(checks.values()):
            raise RuntimeError(f"Écart dans les relevés Notes : {checks}")
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        try:
            if sandbox_id in active_sandboxes():
                wsb("stop", "--id", sandbox_id)
            report["sandbox_stopped"] = sandbox_id not in active_sandboxes()
        finally:
            report["wall_s"] = round(perf_counter() - begin, 3)
            write_report(output, report)
    if not report["sandbox_stopped"]:
        raise RuntimeError("L'arrêt du bac Notes n'est pas confirmé.")
    report["status"] = "passed"
    write_report(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.runtime.resolve(strict=True), args.output.resolve())
    print(json.dumps({name: report[name] for name in ("status", "capture_wall_s", "wall_s")}), flush=True)


if __name__ == "__main__":
    main()
