"""Parcours Notes avec observation RapidOCR dans Windows Sandbox."""

from importlib.metadata import distribution
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from time import perf_counter
from uuid import UUID, uuid4

from bench.run_guided_repair import BENCH, file_hash, write_report, wsb
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .model_resources import reserve_model
from .notes_repair import stage_git
from .notes_sandbox import POWERSHELL, active_sandboxes, guest_exit, read_profile, require_step_permission, wait_for_guest
from .planning import PlanningError, compile_goal

PROTOCOL_FILE = Path(__file__).with_name("protocols") / "notes-desktop-ocr-v2.json"
VC_RUNTIME = ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")
GUEST_SCRIPTS = ("notes_ocr_guest.py", "run_notes_ocr.ps1", "read_notes_ocr_error.ps1",
                 "measure_ocr.py", "validate_guided_notes.ps1", "probe_notes_isolation.ps1",
                 "probe_guest_channels.ps1")


def load_desktop_protocol(report: dict) -> dict:
    manifest = PROTOCOL_FILE.read_text(encoding="utf-8")
    protocol = json.loads(manifest)
    report["protocol"] = {"version": protocol["version"], "sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest()}
    return protocol


def stage_ocr(stage: Path, wheel_versions: dict[str, str]) -> dict:
    packages = stage / "ocr-packages"
    for name, expected in wheel_versions.items():
        wheel = distribution(name)
        if wheel.version != expected or wheel.files is None:
            raise RuntimeError(f"Le paquet local {name} doit être en version {expected}.")
        for member in wheel.files:
            if member.is_absolute() or ".." in member.parts or member.suffix == ".pyc":
                continue
            destination = packages / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wheel.locate_file(member), destination)
    models = packages / "rapidocr_onnxruntime" / "models"
    return {"packages": wheel_versions, "model_sha256": {m.name: file_hash(m) for m in sorted(models.glob("*.onnx"))}}


def prepare_desktop(stage: Path, profile: str, report: dict, protocol: dict, git: dict) -> None:
    ocr = report["ocr"] = stage_ocr(stage, protocol["ocr"]["packages"])
    portable = stage / "python"
    system = Path(os.environ["SystemRoot"]) / "System32"
    ocr["native_dependencies"] = {}
    for name in VC_RUNTIME:
        shutil.copyfile(system / name, portable / name)
        ocr["native_dependencies"][name] = file_hash(portable / name)
    for name in GUEST_SCRIPTS:
        shutil.copyfile(BENCH / "harness" / name, stage / name)
    shutil.copyfile(BENCH / "notes" / "notes_app.py", stage / "notes_app.py")
    verify_frozen_inputs(stage, profile, ocr, git, protocol)
    report["protocol"]["inputs_verified"] = True


def verify_frozen_inputs(stage: Path, profile: str, ocr: dict, git: dict, protocol: dict) -> None:
    inputs = {name: (stage / name).read_text(encoding="utf-8")
              for name in (*GUEST_SCRIPTS, "notes_app.py", "control/notes_store.py")}
    inputs["akasha-bench.wsb"] = profile
    input_hashes = {name: hashlib.sha256(content.encode("utf-8")).hexdigest() for name, content in inputs.items()}
    python_hashes = {name: file_hash(stage / "python" / name) for name in protocol["python_sha256"]}
    observed = {"inputs_sha256": input_hashes, "python_sha256": python_hashes, "ocr": ocr, "git": git}
    for key, values in observed.items():
        if values != protocol[key]:
            raise RuntimeError(f"Entrées différentes du protocole bureau figé ({key}).")


def desktop_patch_matches(repair: Path, protocol: dict) -> bool:
    return (
        file_hash(repair / "proposal.diff") == protocol["diff_sha256"]
        and (repair / "notes-store.sha256").read_text(encoding="ascii").strip() == protocol["patched_store_sha256"]
    )


def decode_desktop(code: int) -> dict:
    if not 0x4700 <= code <= 0x471F:
        raise RuntimeError(f"Observation bureau Notes interrompue (code invité {code}).")
    return {
        "ocr_save_button_used": bool(code & 1),
        "app_restarted": bool(code & 2),
        "ocr_note_selected_after_restart": bool(code & 4),
        "ocr_content_visible": bool(code & 8),
        "sqlite_exact_row": bool(code & 16),
    }


def guest_diagnostic(sandbox_id: str, guest_input: str, tag: str) -> str:
    output = bytearray()
    for offset in range(0, 96, 3):
        code = guest_exit(sandbox_id, f"{POWERSHELL} -File {guest_input}\\read_notes_ocr_error.ps1 "
                                     f"-Tag {tag} -Offset {offset}")
        if code >> 24 != 0x48:
            break
        part = (code & 0xFFFFFF).to_bytes(3, "little").rstrip(b"\0")
        output.extend(part)
        if len(part) != 3:
            break
    return output.decode("ascii")


def verify_desktop(sandbox_id: str, guest_input: str, tag: str, report: dict) -> None:
    with reserve_model("onnxruntime", 4096, inside_sandbox=True) as residency:
        code = guest_exit(sandbox_id, f"{POWERSHELL} -Sta -File {guest_input}\\run_notes_ocr.ps1 -Tag {tag}")
    report["residency"] = residency
    report["guest_exit_code"] = code
    if code != 0x471F:
        report["guest_diagnostic"] = guest_diagnostic(sandbox_id, guest_input, tag)
    report["desktop"] = decode_desktop(code)


def run_desktop(goal: dict, catalog: dict, runtime: Path, output: Path, diff: Path) -> dict:
    compile_goal(goal, catalog)
    observer = catalog["notes.form_ocr", "1.0.0"]["manifest"]
    output.mkdir(parents=True)
    report = {"status": "running", "goal_id": goal["goal_id"], "observer": observer["capability_id"]}
    sandbox_id = None
    wall = perf_counter()
    try:
        if active_sandboxes():
            raise RuntimeError("Une session Windows Sandbox est déjà active.")
        protocol = load_desktop_protocol(report)
        diff_hash = protocol["diff_sha256"]
        if file_hash(diff) != diff_hash:
            raise RuntimeError("L'empreinte du diff diffère de celle de la réparation Notes validée.")
        profile = read_profile()
        tag = secrets.token_hex(4)
        guest_input = fr"C:\AkashaGuidedInput-{tag}"
        stage = output / "input"
        stage.mkdir()
        report["git"] = stage_git(stage)
        shutil.copytree(runtime, stage / "python")
        original = BENCH / "notes" / "notes_store.py"
        frozen_hash = file_hash(original)
        (stage / "control").mkdir()
        source = stage / "control" / "notes_store.py"
        source.write_bytes(original.read_text(encoding="utf-8").encode("utf-8"))
        (stage / "rbitnet-1").mkdir()
        shutil.copyfile(diff, stage / "rbitnet-1" / "proposal.diff")
        (stage / "rbitnet-1" / "notes-store.sha256").write_text(protocol["patched_store_sha256"], encoding="ascii")
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        prepare_desktop(stage, profile, report, protocol, report["git"])

        sandbox_id = str(uuid4())
        report["sandbox_id"] = sandbox_id
        write_report(output, report)
        if str(UUID(wsb("start", "--id", sandbox_id, "--config", profile)["Id"])) != sandbox_id:
            raise RuntimeError("Windows Sandbox a renvoyé une identité différente.")
        wait_for_guest(sandbox_id)
        wsb("share", "--id", sandbox_id, "--host-path", str(stage), "--sandbox-path", guest_input)
        mount = guest_exit(sandbox_id, f"{POWERSHELL} -File {guest_input}\\probe_notes_isolation.ps1 -Tag {tag}")
        channels = guest_exit(sandbox_id, f"{POWERSHELL} -File {guest_input}\\probe_guest_channels.ps1")
        report["isolation"] = {"read_only_mount": mount == 0x450F, "guest_channels_checked": channels in (0x410F, 0x411F)}
        if not all(report["isolation"].values()):
            raise RuntimeError("Preuve de confinement incomplète pour le parcours bureau.")
        for action in ("observe", "edit", "test"):
            require_step_permission({"id": "notes-desktop", "action": action}, goal, active_sandboxes() == [sandbox_id])
        apply_code = guest_exit(sandbox_id, f"{POWERSHELL} -File {guest_input}\\validate_guided_notes.ps1 "
                                           f"-Tag {tag} -InputName rbitnet-1 -ApplyDiff")
        report["diff_applied"] = apply_code == 0x4602
        if not report["diff_applied"]:
            raise RuntimeError(f"Application du diff de référence interrompue ({apply_code}).")
        verify_desktop(sandbox_id, guest_input, tag, report)
        report["isolation"]["host_unchanged"] = (
            file_hash(original) == frozen_hash
            and file_hash(diff) == diff_hash and desktop_patch_matches(stage / "rbitnet-1", protocol)
            and (stage / "isolation-sentinel.txt").read_text(encoding="ascii") == tag
            and not (stage / "isolation-probe.tmp").exists()
        )
        if all(report["desktop"].values()) and report["isolation"]["host_unchanged"]:
            report["status"] = "passed"
        else:
            raise RuntimeError("L'observation ou la persistance du parcours bureau a échoué.")
    except PlanningError as exc:
        report.update(status="failed", error=exc.error.as_dict())
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        report.update(status="failed", error=AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(exc)).as_dict())
    finally:
        if sandbox_id:
            try:
                if sandbox_id in active_sandboxes():
                    wsb("stop", "--id", sandbox_id)
                report["sandbox_stopped"] = sandbox_id not in active_sandboxes()
                if not report["sandbox_stopped"]:
                    raise RuntimeError("L'arrêt du bac dédié n'est pas confirmé.")
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                report.update(status="failed", cleanup_error=str(exc))
        report["wall_s"] = round(perf_counter() - wall, 3)
        write_report(output, report)
    return report
