"""Exerce la file de maintenance du desktop Notes à travers un redémarrage."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4

from akasha_brain.bounded_evolution import BoundedEvolution, Policy
from akasha_brain.desktop import Desktop
from akasha_brain.desktop_tasks import NotesTasks, checked_task_diff
from akasha_brain.integrated_evolution import IntegratedEvolution
from akasha_brain.notes_link_promotion import digest, ssh_keygen
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.phase6_runtime import Phase6Session, install_session, sign_with_key
from akasha_brain.phase6_skill import GENERATION, REUSE
from bench.run_guided_repair import BENCH, file_hash, write_report
from bench.run_phase6_integrated import ARCHIVES, archive, restore_qualification
from bench.run_phase6_skill_evolution import MODEL_RAM_MIB, prepare_library


def provision(output: Path, source: Path, archives: dict[str, Path], key: Path) -> dict:
    output.mkdir(parents=True)
    result = ssh_keygen(["-y", "-f", str(key)], b"")
    if result.returncode != 0:
        raise RuntimeError("La clé d'évolution fournie est indisponible.")
    public_key = " ".join(result.stdout.decode("ascii").split()[:2])
    reports, fingerprints, cycles = {}, {}, {}
    for family, folder in archives.items():
        report, fingerprint = archive(folder, family)
        policy = replace(Policy(**report["policy"]),
                         freeze_sha256=digest({"prior": report["policy"]["freeze_sha256"], "archive": fingerprint}))
        cycles[family] = BoundedEvolution(output / f"{family}.sqlite", str(uuid4()), policy, public_key)
        cycles[family].initialize()
        reports[family], fingerprints[family] = report, fingerprint
    coordinator = IntegratedEvolution(output / "integrated.sqlite", cycles)
    coordinator.initialize()
    for family, report in reports.items():
        restore_qualification(coordinator, family, report, lambda document: sign_with_key(key, document))
    prepare_library(source, output)
    install_session(output, cycles, public_key)
    return fingerprints


class FaultyRouteSession(Phase6Session):
    def observe_route(self, runtime, output):
        return super().observe_route(runtime, output, store="faulty")


def wait_for(root, future, timeout: float):
    stop = monotonic() + timeout
    while not future.done():
        if monotonic() >= stop:
            raise TimeoutError("Le desktop n'a pas terminé son travail dans le budget de l'essai.")
        root.update()
        sleep(0.15)
    future.result()
    root.update()


def test_process(args) -> dict:
    session = (FaultyRouteSession if args.step == "resume" else Phase6Session)(args.session, args.key)
    if args.step == "status":
        return {"status": session.status()}
    if args.step == "resume":
        session.set_paused(False)
    tasks = NotesTasks(args.runs, args.runtime, RbitnetPaths(*args.rbitnet, model_ram_mib=MODEL_RAM_MIB), False,
                      integrated=session)
    from tkinter import Tk

    root = Tk()
    root.withdraw()
    try:
        desktop = Desktop(root, tasks)
        if args.step == "operator":
            before = session.status()
            desktop.integrated_rollback.invoke()
            return {"before": before, "after": session.status(), "banner": desktop.integrated_label.cget("text")}
        # La file de fond a été remplie par le constructeur normal de NotesTasks.
        if args.step == "resume":
            wait_for(root, tasks.scheduler.submit(lambda: None, background=True), 250)
        before = session.status()
        folder = desktop.launch()
        if folder is None:
            raise RuntimeError(f"Le bouton Notes n'a pas lancé la tâche : {desktop.message}")
        wait_for(root, tasks.execution, 280)
        wait_for(root, tasks.scheduler.submit(lambda: None, background=True), 250)
        task = json.loads((folder / "task.json").read_bytes())
        if task["status"] != "passed":
            raise RuntimeError(task.get("error", {}).get("message", "Échec de la tâche Notes."))
        result = json.loads((folder / "result/report.json").read_bytes())
        step = next(row for row in result["trace"] if row["id"] == "generate_diff")
        job = session.job(folder.name)
        desktop.update_integrated()
        return {"task": folder.name, "before": before, "after": session.status(),
                "execution": result["phase6_execution"], "job": job, "task_status": result["status"],
                "sandbox": result["sandbox_id"], "sandbox_stopped": result["sandbox_stopped"],
                "tests_passed": next(row["result"]["passed"] for row in result["trace"] if row["id"] == "verify"),
                "desktop": next(row["result"]["desktop"] for row in result["trace"] if row["id"] == "verify_desktop"),
                "checked_diff_in_history": checked_task_diff(folder, step) is not None,
                "banner": desktop.integrated_label.cget("text")}
    finally:
        root.destroy()


def validate(output: Path, phase1: Path, archives: dict[str, Path], runtime: Path, rbitnet: list[Path]) -> dict:
    started = monotonic()
    output.mkdir(parents=True)
    session_root = output / "session"
    runs = output / "runs"
    sources = ("akasha_brain/desktop.py", "akasha_brain/desktop_tasks.py", "akasha_brain/phase6_runtime.py",
               "akasha_brain/phase6_skill.py", "akasha_brain/integrated_evolution.py", "bench/run_phase6_desktop.py")
    report = {"protocol": "phase6-desktop-restart-v1", "status": "running", "checks": {},
              "sources_sha256": {source: file_hash(BENCH.parent / source) for source in sources}}
    with TemporaryDirectory(prefix="akasha-phase6-desktop-") as directory:
        key = Path(directory) / "signer"
        generated = ssh_keygen(["-q", "-t", "ed25519", "-N", "", "-f", str(key)], b"")
        if generated.returncode:
            raise RuntimeError("La clé Ed25519 de l'essai n'a pas pu être créée.")
        report["archives_sha256"] = provision(session_root, phase1, archives, key)
        Phase6Session(session_root, key).set_paused(True)

        def process(step: str, session: Path = session_root, *, name: str | None = None):
            label = name or step
            path = output / f"{label}.json"
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", "-m", "bench.run_phase6_desktop", "_process", step,
                 "--session", str(session), "--key", str(key), "--runs", str(runs), "--runtime", str(runtime),
                 "--rbitnet", *map(str, rbitnet), "--record", str(path)],
                cwd=BENCH.parent, timeout=540, creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True, encoding="utf-8", errors="replace",
            )
            if completed.returncode:
                raise RuntimeError(f"Le processus desktop {label} a échoué.\n{completed.stderr}")
            result = json.loads(path.read_bytes())
            report[label] = result
            write_report(output, report)
            print(f"{label}: {result.get('execution', result.get('status', result.get('after')))}", flush=True)
            return result

        first = process("launch")
        second = process("resume")
        resumed = Phase6Session(session_root, key).job(first["task"])
        reopened = process("status", name="reopened")
        operator_session = output / "operator-session"
        provision(operator_session, phase1, archives, key)
        requested = process("operator", operator_session)
        operator_reopened = process("status", operator_session, name="operator_reopened")
        report["resumed_initial_job"] = resumed
        report["checks"] = {
            "task_triggered_while_paused": first["job"]["state"] == "waiting" and first["before"]["paused"],
            "first_task_used_qualified_skill": first["execution"] == {"skill": REUSE, "memory": "contextual"},
            "pending_job_resumed_on_desktop_start": resumed["state"] == "finished"
                and set(resumed["detail"]["route"]["mismatches"]) == {"sqlite.row_count", "sqlite.exact_fixture_present"},
            "parent_selected_by_next_task": second["before"]["autonomy_phase"] == 3
                and second["execution"] == {"skill": GENERATION, "memory": "contextual"},
            "no_candidate_trial_after_downgrade": second["job"]["state"] == "finished"
                and "route" not in second["job"]["detail"],
            "independent_working_sandboxes": first["sandbox"] != second["sandbox"]
                and all(trial["sandbox_stopped"] for trial in (first, second)),
            "normal_desktop_results_verified": all(
                trial["task_status"] == "passed" and trial["tests_passed"] == 4 and all(trial["desktop"].values())
                and trial["checked_diff_in_history"] for trial in (first, second)
            ),
            "reopened_phase_3_with_no_pending_tasks": reopened["status"]["autonomy_phase"] == 3
                and reopened["status"]["jobs"] == {"finished": 2},
            "operator_rollback_stayed_active_after_restart": requested["before"]["autonomy_phase"] == 6
                and requested["after"]["autonomy_phase"] == 3
                and set(requested["after"]["rollback_proofs"]) == {"operator"}
                and requested["after"]["effective"] == second["before"]["effective"]
                and operator_reopened["status"] == requested["after"],
            "sources_unchanged": report["sources_sha256"] == {source: file_hash(BENCH.parent / source) for source in sources},
        }
        if not all(report["checks"].values()):
            raise RuntimeError(f"Écart sur le parcours desktop : {report['checks']}")
    report["status"] = "passed"
    report["wall_s"] = round(monotonic() - started, 3)
    write_report(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for mode in ("prepare", "validate"):
        command = commands.add_parser(mode)
        for name in (*ARCHIVES, "phase1", "output"):
            command.add_argument(f"--{name}", type=Path, required=True)
        if mode == "prepare":
            command.add_argument("--key", type=Path, required=True)
        else:
            command.add_argument("--runtime", type=Path, required=True)
            command.add_argument("--rbitnet", type=Path, nargs=3, required=True)
    worker = commands.add_parser("_process")
    worker.add_argument("step", choices=("launch", "resume", "status", "operator"))
    for name in ("session", "key", "runs", "runtime", "record"):
        worker.add_argument(f"--{name}", type=Path, required=True)
    worker.add_argument("--rbitnet", type=Path, nargs=3, required=True)
    args = parser.parse_args()
    if args.command == "_process":
        args.record.write_text(json.dumps(test_process(args), ensure_ascii=False, indent=2), encoding="utf-8")
        return
    archives = {name: getattr(args, name).resolve(strict=True) for name in ARCHIVES}
    if args.command == "prepare":
        result = provision(args.output.resolve(), args.phase1.resolve(strict=True), archives, args.key.resolve(strict=True))
    else:
        result = validate(args.output.resolve(), args.phase1.resolve(strict=True), archives, args.runtime.resolve(strict=True),
                          [path.resolve(strict=True) for path in args.rbitnet])["checks"]
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
