"""Contrôles communs aux parcours Notes dans Windows Sandbox."""

from time import sleep
from uuid import UUID
from xml.etree import ElementTree

from bench.run_guided_repair import BENCH, wsb
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .planning import PlanningError

CHANNELS = ("Networking", "ClipboardRedirection", "AudioInput", "VideoInput", "PrinterRedirection", "VGpu")
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
