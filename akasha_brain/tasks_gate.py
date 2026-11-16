"""Porte facultative du routage Tâches, évaluée hors ligne dans Windows Sandbox."""

import json
from pathlib import Path
import secrets
import shutil
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import UUID, uuid4

from bench.run_guided_repair import BENCH, wsb
from contracts.akasha_contracts.authz import authorize

from .notes_sandbox import CHANNELS, POWERSHELL, active_sandboxes, guest_exit, read_profile, wait_for_guest
from .planning import PlanningError
from .project_dependencies import stage_dependencies
from .tasks_gate_worker import PACKET, SAMPLES, STATUSES, TIMING_UNIT_NS, VERSION, WHEEL, WHEEL_SHA256, validate


def signals(tool: str, **updates) -> dict:
    values = {"tool": tool, "authorized": True, "context": True, "capability": True, "certain": True,
              "risk": 0, "budget": None, "confirmation_needed": False, "confirmation_given": False}
    values.update(updates)
    validate(values)
    return values


def decode(packet: int) -> dict:
    if packet & ~0x0FFFFFFF != PACKET or (packet & 3) not in STATUSES or ((packet >> 2) & 3) not in STATUSES:
        raise RuntimeError(f"La réponse de la porte en bac est invalide ({packet}).")
    return {"deterministic": STATUSES[packet & 3], "akasha_model": STATUSES[(packet >> 2) & 3],
            "deterministic_us": ((packet >> 4) & 0xFFF) * TIMING_UNIT_NS / 1000,
            "akasha_model_us": ((packet >> 16) & 0xFFF) * TIMING_UNIT_NS / 1000}


def evaluate(runtime: Path, request: Path, decisions: list[dict], staging_parent: Path, *, samples: int = SAMPLES) -> dict:
    if not 1 <= len(decisions) <= 32:
        raise ValueError("La porte accepte une à trente-deux décisions typées.")
    if samples not in (1, SAMPLES):
        raise ValueError("Nombre d'échantillons inattendu.")
    for row in decisions:
        validate(row)
    if active_sandboxes():
        raise RuntimeError("Une session Windows Sandbox est déjà active.")
    staging_parent.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    with TemporaryDirectory(prefix="tasks-gate-", dir=staging_parent) as folder:
        stage = Path(folder)
        dependency, = stage_dependencies(BENCH.parent, [request], stage)
        if (dependency["name"], dependency["version"], dependency["filename"], dependency["sha256"],
                dependency["license"]) != ("akasha-model", VERSION, WHEEL, WHEEL_SHA256, "MIT"):
            raise ValueError("La porte exige la roue épinglée d'akasha-model.")
        shutil.copytree(runtime, stage / "python")
        for name in ("probe_notes_isolation.ps1", "probe_guest_channels.ps1"):
            shutil.copyfile(BENCH / "harness" / name, stage / name)
        shutil.copyfile(Path(__file__).with_name("tasks_gate_worker.py"), stage / "worker.py")
        (stage / "signals.json").write_text(json.dumps({"decisions": decisions, "samples": samples}), encoding="ascii")
        tag = secrets.token_hex(4)
        guest_path = fr"C:\AkashaGuidedInput-{tag}"
        (stage / "isolation-sentinel.txt").write_text(tag, encoding="ascii")
        identity = str(uuid4())
        try:
            if str(UUID(wsb("start", "--id", identity, "--config", read_profile())["Id"])) != identity:
                raise RuntimeError("Identifiant du bac inattendu.")
            wait_for_guest(identity)
            wsb("share", "--id", identity, "--host-path", str(stage), "--sandbox-path", guest_path)
            mount = guest_exit(identity, f"{POWERSHELL} -File {guest_path}\\probe_notes_isolation.ps1 -Tag {tag}")
            channels = guest_exit(identity, f"{POWERSHELL} -File {guest_path}\\probe_guest_channels.ps1")
            refused = authorize({"risk_class": "R1", "confinement_verified":
                                 mount == 0x450F and channels in (0x410F, 0x411F) and active_sandboxes() == [identity]})
            if refused:
                raise PlanningError(refused)
            worker = f"{guest_path}\\python\\python.exe -I -B -X utf8 {guest_path}\\worker.py {tag}"
            observed = [decode(guest_exit(identity, f"{worker} {index}")) for index in range(len(decisions))]
        finally:
            if identity in active_sandboxes():
                wsb("stop", "--id", identity)
            if identity in active_sandboxes():
                raise RuntimeError("Arrêt du bac de décision non confirmé.")
    return {"dependency": dependency, "installation": "offline", "path": "A", "sandbox_id": identity,
            "sandbox_stopped": True, "read_only_input": True, "disabled_channels": list(CHANNELS),
            "channel_probe": channels, "samples_per_decision": samples, "decisions": observed,
            "wall_s": round(perf_counter() - started, 3)}
