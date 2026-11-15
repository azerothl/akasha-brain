"""Exécution du graphe de référence Notes dans un bac dédié."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shutil
import subprocess
from time import perf_counter, sleep
from uuid import UUID, uuid4
from xml.etree import ElementTree

from bench.run_guided_repair import (
    BENCH, MAX_TOKENS, SEEDS, TEMPERATURE, check_faulty, file_hash, guest_validate, method_text, prepare,
    write_report, wsb,
)
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .notes_repair import RbitnetPaths, generate_patch, load_repair_prompt, retry_prompt, stage_git
from .planning import PlanningError, compile_goal

CHANNELS = ("Networking", "ClipboardRedirection", "AudioInput", "VideoInput", "PrinterRedirection", "VGpu")
TESTS = (
    "test_saved_note_survives_restart",
    "test_two_notes_with_accents_multiline_survive_restart",
    "test_save_acknowledged_in_session",
    "test_select_redisplays_content",
)
POWERSHELL = (
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe "
    "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass"
)


def require_step_permission(step: dict, goal: dict, confinement_verified: bool) -> None:
    if step["action"] not in goal["constraints"]["allowed_actions"]:
        raise PlanningError(AkashaError(
            ErrorCode.PERMISSION_DENIED, "Action hors périmètre de l'objectif.",
            {"step": step["id"], "action": step["action"]},
        ))
    denied = authorize({"risk_class": goal["risk_class"], "confinement_verified": confinement_verified})
    if denied:
        raise PlanningError(denied)


def authorization_controls(step: dict, goal: dict) -> dict:
    out_of_scope = {**goal, "constraints": {**goal["constraints"], "allowed_actions": []}}
    results = {}
    for name, request, isolated in (("missing_confinement", goal, False), ("out_of_scope", out_of_scope, True)):
        try:
            require_step_permission(step, request, isolated)
        except PlanningError as denied:
            if denied.error.code == ErrorCode.PERMISSION_DENIED:
                results[name] = denied.error.code.value
                continue
            raise
        raise RuntimeError(f"Le contrôle d'autorisation a accepté {name}.")
    return results


def read_profile() -> str:
    source = (BENCH / "harness" / "akasha-bench.wsb").read_text(encoding="utf-8")
    root = ElementTree.fromstring(source)
    folders = root.find("MappedFolders")
    expected = set(CHANNELS) | {"MappedFolders", "MemoryInMB"}
    if (root.tag != "Configuration" or {item.tag for item in root} != expected
            or len(root) != len(expected) or any(root.findtext(name) != "Disable" for name in CHANNELS)
            or folders is None or len(folders) or (folders.text or "").strip()):
        raise RuntimeError("Profil Windows Sandbox incompatible avec le banc durci.")
    return source


def active_sandboxes() -> list[str]:
    return [str(UUID(item["Id"])) for item in wsb("list").get("WindowsSandboxEnvironments", ())]


def guest_exit(sandbox_id: str, command: str) -> int:
    return wsb("exec", "--id", sandbox_id, "--run-as", "ExistingLogin", "--command", command)["ExitCode"]


def wait_for_guest(sandbox_id: str) -> None:
    wsb("connect", "--id", sandbox_id)
    for _ in range(12):
        try:
            if guest_exit(sandbox_id, r"C:\Windows\System32\cmd.exe /c exit 0") == 0:
                return
        except RuntimeError:
            pass
        sleep(1)
    raise RuntimeError("La session utilisateur du bac n'est pas prête.")


def decode_validation(code: int) -> dict:
    if not 0x50000000 <= code <= 0x5001FFFF:
        raise RuntimeError(f"Rapport de tests invité invalide ({code}).")
    states = ("passed", "failed", "error", "skipped")
    tests = [{"name": name, "status": states[(code >> (8 + 2 * index)) & 3]}
             for index, name in enumerate(TESTS)]
    return {
        "tests": tests,
        "passed": sum(test["status"] == "passed" for test in tests),
        "diagnosis": (code >> 16) & 1,
        "pytest_exit": (code >> 4) & 15,
        "sqlite_verifier_exit": code & 15,
        "sqlite_verdict": "passed" if not (code & 15) else "failed",
    }


def run_notes(goal: dict, catalog: dict, runtime: Path, output: Path, repair: RbitnetPaths | None = None,
              *, first_diff_seed: int | None = None) -> dict:
    plan = compile_goal(goal, catalog, rbitnet=repair is not None)
    seeds = (first_diff_seed,) if first_diff_seed is not None else SEEDS[0]
    output.mkdir(parents=True)
    report = {"graph": plan, "status": "running", "trace": []}
    sandbox_id = None
    wall = perf_counter()
    try:
        if active_sandboxes():
            raise RuntimeError("Une session Windows Sandbox est déjà active.")
        profile = read_profile()
        tag = secrets.token_hex(4)
        guest_input = fr"C:\AkashaGuidedInput-{tag}"
        stage = output / "input"
        stage.mkdir()
        fixtures = prepare(stage, runtime)
        sources = {"control": BENCH / "notes" / "notes_store.py"}
        if repair is None:
            sources["baseline"] = BENCH / "reference" / "notes_reference_store.py"
        source_hashes = {name: file_hash(path) for name, path in sources.items()}
        staged_hashes = {}
        for name, source in sources.items():
            folder = stage / name
            folder.mkdir()
            staged_source = folder / "notes_store.py"
            staged_source.write_bytes(source.read_text(encoding="utf-8").encode("utf-8"))
            staged_hashes[name] = file_hash(staged_source)
        if repair:
            repair_prompt = load_repair_prompt()
            report["repair"] = {"backend": "cpu", "model": repair.model.name, "hashes": repair.verify(),
                                "git": stage_git(stage), "seeds": seeds, "temperature": TEMPERATURE,
                                "max_tokens": MAX_TOKENS, "prompt_version": repair_prompt["version"],
                                "prompt_sha256": repair_prompt["sha256"]}
        for script in ("probe_notes_isolation.ps1", "probe_guest_channels.ps1"):
            shutil.copyfile(BENCH / "harness" / script, stage / script)
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        (stage / "notes-test-cases.json").write_text(json.dumps(TESTS), encoding="ascii")

        sandbox_id = str(uuid4())
        report["sandbox_id"] = sandbox_id
        write_report(output, report)
        started_id = str(UUID(wsb("start", "--id", sandbox_id, "--config", profile)["Id"]))
        if started_id != sandbox_id:
            raise RuntimeError("Windows Sandbox a renvoyé une identité différente.")
        wait_for_guest(sandbox_id)
        wsb("share", "--id", sandbox_id, "--host-path", str(stage), "--sandbox-path", guest_input)
        mount = guest_exit(sandbox_id, f"{POWERSHELL} -File {guest_input}\\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox_id, f"{POWERSHELL} -File {guest_input}\\probe_guest_channels.ps1")
        report["isolation"] = {
            "declared_disabled_channels": list(CHANNELS),
            "guest_read_input": bool(mount & 1),
            "guest_write_to_input_denied": bool(mount & 2),
            "guest_create_in_input_denied": bool(mount & 4),
            "guest_scratch_write": bool(mount & 8),
            "guest_no_default_route": bool(channels & 1),
            "guest_no_camera": bool(channels & 2),
            "guest_no_audio_capture": bool(channels & 4),
            "guest_no_redirected_printer": bool(channels & 8),
        }
        if mount != 0x450F or channels not in (0x410F, 0x411F):
            raise RuntimeError(f"Preuve de confinement incomplète ({mount}, {channels}).")
        report["authorization_controls"] = authorization_controls(plan["steps"][0], goal)
        write_report(output, report)

        runner = f"{POWERSHELL} -File {guest_input}\\validate_guided_notes.ps1 -Tag {tag} -InputName"
        completed = set()

        @contextmanager
        def trace_step(step, attempt=1):
            row = {**step, "started_at": datetime.now(timezone.utc).isoformat(), "status": "failed"}
            if repair:
                row["attempt"] = attempt
            report["trace"].append(row)
            began = perf_counter()
            try:
                if not set(step["depends_on"]).issubset(completed):
                    raise RuntimeError("Les dépendances du graphe ne sont pas vérifiées.")
                require_step_permission(step, goal, active_sandboxes() == [sandbox_id])
                row["authorization"] = "allowed"
                yield row
                if row["status"] == "passed":
                    completed.add(step["id"])
            finally:
                row["wall_s"] = round(perf_counter() - began, 3)
                write_report(output, report)

        localize, prepare_step, verify = plan["steps"]
        with trace_step(localize) as row:
            results = guest_validate(sandbox_id, tag, "control", locate=True)
            row["result"] = results
            check_faulty(results, locate=True)
            row["status"] = "passed"

        def validate_prepared(name, attempt):
            with trace_step(verify, attempt) as row:
                results = decode_validation(guest_exit(sandbox_id, f"{runner} {name} -VerifyPrepared"))
                row["result"] = results
                if results["passed"] == 4 and results["pytest_exit"] == results["sqlite_verifier_exit"] == 0:
                    row["status"] = "passed"
            return row

        if repair:
            source = (stage / "control" / "notes_store.py").read_text(encoding="utf-8")
            prompt = repair_prompt["text"] + method_text(source)
            for attempt, seed in enumerate(seeds, 1):
                name = f"rbitnet-{attempt}"
                work = output / name
                with trace_step(prepare_step, attempt) as row:
                    proposal = generate_patch(repair, work, stage, source, prompt, seed)
                    row["result"] = proposal
                    if "diff_file" in proposal:
                        code = guest_exit(sandbox_id, f"{runner} {name} -ApplyDiff")
                        proposal["guest_apply_exit"] = code
                        if code == 0x4602:
                            proposal.update(diff_applied=True, git_apply_check=True, guest_sha256_verified=True)
                            row["status"] = "passed"
                        else:
                            proposal["diff_detail"] = f"Guest patch rejected (exit code {code})."
                validation = validate_prepared(name, attempt) if proposal["diff_applied"] else None
                if validation and validation["status"] == "passed":
                    report["accepted_attempt"] = attempt
                    break
                if attempt < len(seeds):
                    prompt = retry_prompt(proposal, validation["result"] if validation else None,
                                          work, source, repair_prompt["requirements"])
                    completed.discard(prepare_step["id"])
            else:
                raise RuntimeError("Aucune proposition Rbitnet n'a satisfait la validation.")
        else:
            with trace_step(prepare_step) as row:
                if guest_exit(sandbox_id, f"{runner} baseline -PrepareReference") != 0x4601:
                    raise RuntimeError("La copie de la référence dans le bac a échoué.")
                row["result"] = {"reference_sha256_verified_in_guest": True}
                row["status"] = "passed"
            if validate_prepared("baseline", 1)["status"] != "passed":
                raise RuntimeError("Les tests ou le vérificateur SQLite ont échoué.")

        originals_intact = all(file_hash(path) == source_hashes[name] for name, path in sources.items())
        staging_intact = (
            (stage / "isolation-sentinel.txt").read_text(encoding="ascii") == tag
            and not (stage / "isolation-probe.tmp").exists()
            and all(file_hash(stage / "fixture" / path) == digest for path, digest in fixtures.items())
            and all(file_hash(stage / name / "notes_store.py") == digest for name, digest in staged_hashes.items())
        )
        report["isolation"].update(host_sources_unchanged=originals_intact, host_staging_unchanged=staging_intact)
        if not originals_intact or not staging_intact:
            raise RuntimeError("L'intégrité du banc hôte n'est pas vérifiée.")
        report["status"] = "passed"
    except PlanningError as exc:
        report["status"] = "failed"
        report["error"] = exc.error.as_dict()
    except (OSError, RuntimeError, ValueError, KeyError, ElementTree.ParseError, subprocess.SubprocessError) as exc:
        report["status"] = "failed"
        report["error"] = AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(exc)).as_dict()
    finally:
        if sandbox_id:
            try:
                if sandbox_id in active_sandboxes():
                    wsb("stop", "--id", sandbox_id)
                report["sandbox_stopped"] = sandbox_id not in active_sandboxes()
                if not report["sandbox_stopped"]:
                    raise RuntimeError("L'arrêt du bac dédié n'est pas confirmé.")
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                report["status"] = "failed"
                report["cleanup_error"] = str(exc)
        report["wall_s"] = round(perf_counter() - wall, 3)
        write_report(output, report)
    return report
