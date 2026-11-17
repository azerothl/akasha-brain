"""Compare deux sélections d'action Notes à politique figée dans Windows Sandbox."""

import argparse
from contextlib import contextmanager
import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter, perf_counter_ns
from uuid import UUID, uuid4

from akasha_brain import desktop_state
from akasha_brain.notes_sandbox import POWERSHELL, active_sandboxes, guest_exit, read_profile, wait_for_guest
from bench.run_guided_repair import BENCH, file_hash, write_report, wsb
from bench.run_phase5_notes_desktop_state import INPUTS, observe

PROTOCOL = BENCH / "phase5_notes_actions.json"
ARMS = ("without_predictor", "with_predictor")


def verify_final(goal: dict, before: dict, after: dict) -> dict:
    """Tranche sur le relevé invité indépendant, commun aux deux bras."""
    window, database = after["window"], after["sqlite"]
    relation = "same" if before["process"]["pid"] == after["process"]["pid"] else "different"
    wanted = goal["exact_fixture_present"]
    return {
        "live": after["process"]["alive"],
        "window": window["title"] == desktop_state.NOTES_WINDOW_TITLE and window["visible"] is True,
        "foreground": window["foreground_owned_by_process"],
        "uia_focus": window["uia_focus_owned_by_process"],
        "pid_relation": goal["pid_relation"] in ("any", relation),
        "integrity": database["integrity_check"] == "ok",
        "rows": database["row_count"] == int(wanted),
        "exact_fixture": database["exact_fixture_present"] == wanted,
    }


def project_plan(before: dict, steps: list[str]) -> dict:
    # Le catalogue borné contient au plus une sauvegarde et une relance finale.
    state = before
    expected = desktop_state.notes_variables(before)
    for step in steps:
        expected = desktop_state.predict_notes_transition(state, step)["expected"]
        state = {**state, "sqlite": {key: expected[f"sqlite.{key}"] for key in state["sqlite"]}}
    return expected


def select_plan(plans: dict, goal: dict, before: dict, *, use_predictor: bool) -> dict:
    """Même admissibilité, même ordre, choix prioritaire si une prévision satisfait le but."""
    initial_present = before["sqlite"]["exact_fixture_present"]
    wanted = goal["exact_fixture_present"]
    allowed = []
    projections = {}
    # Le tri stable départage deux plans de même longueur par l'ordre du catalogue.
    for name, steps in sorted(plans.items(), key=lambda plan: len(plan[1])):
        relation = "different" if "restart" in steps else "same"
        if goal["pid_relation"] not in ("any", relation):
            continue
        if "save" in steps and (initial_present or not wanted):
            continue
        if not steps and initial_present != wanted:
            continue
        allowed.append(name)
        if use_predictor:
            expected = project_plan(before, steps)
            projections[name] = {
                "final": expected,
                "matches_goal": (
                    expected["process.alive"]
                    and expected["window.title"] == desktop_state.NOTES_WINDOW_TITLE
                    and expected["window.visible"] is True
                    and expected["window.foreground_owned_by_process"]
                    and expected["window.uia_focus_owned_by_process"]
                    and expected["sqlite.integrity_check"] == "ok"
                    and expected["sqlite.row_count"] == int(wanted)
                    and expected["sqlite.exact_fixture_present"] == wanted
                ),
            }
    if not allowed:
        raise RuntimeError("Aucun plan admissible pour ce cas.")
    chosen = next((name for name in allowed if name in projections and projections[name]["matches_goal"]), allowed[0])
    return {"admissible": allowed, "projections": projections, "chosen": chosen, "steps": plans[chosen]}


def guest_command(sandbox: str, probe: str, mode: str, pid: int | None = None) -> dict:
    command = f"{probe} -Mode {mode}"
    if pid is not None:
        command += f" -NotesId {pid}"
    if mode == "restart":
        command += " -KeepRestarted"
    return observe(sandbox, command, started_at=datetime.now(UTC).isoformat())


def run_arm(sandbox: str, mount: str, case: dict, plans: dict, arm: str, data: dict, persist, *, selector=None) -> None:
    setup_start = perf_counter()
    tag = secrets.token_hex(4)
    probe = fr"{POWERSHELL} -File {mount}\observe_notes_desktop.ps1 -Tag {tag}"
    app = guest_command(sandbox, probe, "begin")
    if case["initial"] == "saved":
        app = guest_command(sandbox, probe, "save", app["process"]["pid"])
    before = guest_command(sandbox, probe, "observe", app["process"]["pid"])
    initial_goal = {"exact_fixture_present": case["initial"] == "saved", "pid_relation": "same"}
    if not all(verify_final(initial_goal, app, before).values()):
        raise RuntimeError(f"État de départ invalide pour {case['id']} / {arm}.")

    decision_start = perf_counter_ns()
    if selector is None:
        decision = select_plan(plans, case["goal"], before, use_predictor=arm == "with_predictor")
    else:
        decision = selector(plans, case["goal"], before)
    decision_us = (perf_counter_ns() - decision_start) / 1000
    data.update(before=before, decision=decision, decision_us=round(decision_us, 3),
                setup_s=round(perf_counter() - setup_start, 3), actions=[])
    persist()

    execution_start = perf_counter()
    state = before
    for action in decision["steps"]:
        action_start = perf_counter()
        state = guest_command(sandbox, probe, action, state["process"]["pid"])
        data["actions"].append({"action": action, "state": state, "wall_s": round(perf_counter() - action_start, 3)})
    execution_s = round(perf_counter() - execution_start, 3)
    verify_start = perf_counter()
    pid = state["process"]["pid"]
    after = guest_command(sandbox, probe, "observe", pid)
    checks = verify_final(case["goal"], before, after)
    data.update(after=after, verification=checks, success=all(checks.values()), execution_s=execution_s,
                verify_s=round(perf_counter() - verify_start, 3),
                decision_to_verdict_s=round((perf_counter_ns() - decision_start) / 1e9, 3))
    if guest_exit(sandbox, f"{probe} -Mode close -NotesId {pid}") != 0x4601:
        raise RuntimeError(f"Arrêt Notes non confirmé pour {case['id']} / {arm}.")
    data["closed"] = True
    persist()
    print(f"{case['id']} / {arm}: {decision['chosen']}, "
          f"vérifié={data['success']}, {data['decision_to_verdict_s']:.3f} s", flush=True)


@contextmanager
def isolated_notes_sandbox(stage: Path, tag: str, profile: str, evidence: dict, persist):
    started = perf_counter()
    sandbox = evidence["sandbox_id"] = str(uuid4())
    if active_sandboxes():
        raise RuntimeError("Une autre session Windows Sandbox est ouverte.")
    mount = fr"C:\AkashaGuidedInput-{tag}"
    try:
        if str(UUID(wsb("start", "--id", sandbox, "--config", profile)["Id"])) != sandbox:
            raise RuntimeError("Identité inattendue pour le bac.")
        wait_for_guest(sandbox)
        if active_sandboxes() != [sandbox]:
            raise RuntimeError("Le bac Notes doit être l'unique session active.")
        wsb("share", "--id", sandbox, "--host-path", str(stage), "--sandbox-path", mount)
        isolation = guest_exit(sandbox, fr"{POWERSHELL} -File {mount}\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox, fr"{POWERSHELL} -File {mount}\probe_guest_channels.ps1")
        evidence["isolation"] = {"mount_and_scratch_exit": isolation, "channels_exit": channels}
        if isolation != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError("Les sondes d'isolation de Notes ont échoué.")

        yield sandbox, mount
    finally:
        if sandbox in active_sandboxes():
            wsb("stop", "--id", sandbox)
        evidence["sandbox_stopped"] = sandbox not in active_sandboxes()
        evidence["wall_s"] = round(perf_counter() - started, 3)
        persist()
    if not evidence["sandbox_stopped"]:
        raise RuntimeError("Arrêt du bac non confirmé.")


def run_pair(case: dict, stage: Path, tag: str, profile: str, plans: dict, pair: dict, persist) -> None:
    with isolated_notes_sandbox(stage, tag, profile, pair, persist) as (sandbox, mount):
        arms = pair["arms"]
        for arm in case["order"]:
            arms[arm] = {}
            run_arm(sandbox, mount, case, plans, arm, arms[arm], persist)
        left, right = (arms[arm] for arm in ARMS)
        if (left["before"]["sqlite"] != right["before"]["sqlite"]
                or left["before"]["window"] != right["before"]["window"]
                or left["decision"]["admissible"] != right["decision"]["admissible"]):
            raise RuntimeError(f"Départ ou admissibilité non appariés pour {case['id']}.")
        pair["matched_initial_state_and_admissibility"] = True


def run(runtime: Path, output: Path) -> dict:
    started = perf_counter()
    profile = read_profile()
    protocol = json.loads(PROTOCOL.read_bytes())
    for case in protocol["cases"]:
        if set(case["order"]) != set(ARMS) or len(case["order"]) != len(ARMS):
            raise ValueError(f"Il faut les deux bras pour {case['id']}.")
    output.mkdir(parents=True)
    stage = output / "input"
    stage.mkdir()
    shutil.copytree(runtime, stage / "python")
    for name, source in INPUTS.items():
        shutil.copyfile(BENCH / source, stage / name)
    tag = secrets.token_hex(4)
    (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
    sources = {"cases_and_policy": PROTOCOL, "runner": Path(__file__),
               "predictor": Path(desktop_state.__file__), "sandbox_profile": BENCH / "harness/akasha-bench.wsb",
               **{name: stage / name for name in INPUTS}}
    hashes = {name: file_hash(path) for name, path in sources.items()}
    report = {"status": "running", **protocol, "sha256": hashes, "pairs": {}}

    def persist():
        write_report(output, report)

    persist()
    try:
        for case in protocol["cases"]:
            pair = report["pairs"][case["id"]] = {"arms": {}}
            run_pair(case, stage, tag, profile, protocol["plans"], pair, persist)
        if hashes != {name: file_hash(path) for name, path in sources.items()}:
            raise RuntimeError("Un intrant a changé pendant l'évaluation.")
        summary = report["summary"] = {}
        for arm in ARMS:
            records = [pair["arms"][arm] for pair in report["pairs"].values()]
            summary[arm] = {
                "verified": sum(record["success"] for record in records),
                "total": len(records),
                "median_decision_us": round(median(record["decision_us"] for record in records), 3),
                "sum_decision_to_verdict_s": round(sum(record["decision_to_verdict_s"] for record in records), 3),
            }
        report["status"] = "completed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["wall_s"] = round(perf_counter() - started, 3)
        persist()
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
