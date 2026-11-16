"""Admission des moteurs locaux dans la session Windows de l'utilisateur."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
import subprocess
from threading import Lock
from time import perf_counter

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .planning import PlanningError

MIB = 1024 * 1024
DEFAULT_RAM_MIB = 8192
DEFAULT_VRAM_MIB = 8192
_process_lease = Lock()


def unavailable(reason: str, **details):
    raise PlanningError(AkashaError(
        ErrorCode.RESIDENCY_UNAVAILABLE, "Ressources d'inférence indisponibles.", {"reason": reason, **details},
    ))


@contextmanager
def inference_lease():
    if not _process_lease.acquire(blocking=False):
        unavailable("inference_busy")
    handle = None
    acquired = False
    try:
        if os.name == "nt":
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
            api.CreateMutexW.restype = wintypes.HANDLE
            api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            api.WaitForSingleObject.restype = wintypes.DWORD
            api.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            api.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = api.CreateMutexW(None, False, r"Local\AkashaBrainInference")
            if not handle:
                unavailable("inference_lease_unavailable")
            result = api.WaitForSingleObject(handle, 0)
            acquired = result in (0, 0x80)  # Disponible ou libéré par la fin du processus précédent.
            if not acquired:
                unavailable("inference_busy" if result == 0x102 else "inference_lease_unavailable")
        yield
    finally:
        if handle:
            if acquired:
                api.ReleaseMutex(handle)
            api.CloseHandle(handle)
        _process_lease.release()


class WindowsMemory(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD), ("load", wintypes.DWORD),
        ("total_physical", ctypes.c_uint64), ("available_physical", ctypes.c_uint64),
        ("total_page", ctypes.c_uint64), ("available_page", ctypes.c_uint64),
        ("total_virtual", ctypes.c_uint64), ("available_virtual", ctypes.c_uint64),
        ("available_extended", ctypes.c_uint64),
    ]


def available_ram() -> int:
    if os.name == "nt":
        status = WindowsMemory(length=ctypes.sizeof(WindowsMemory))
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(WindowsMemory),)
        if not api.GlobalMemoryStatusEx(ctypes.byref(status)):
            unavailable("ram_measurement_unavailable")
        return status.available_physical // MIB
    return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // MIB


def available_vram() -> int:
    try:
        return int(subprocess.check_output(
            ["nvidia-smi", "--id=0", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        unavailable("cuda_device_unavailable")


@contextmanager
def reserve_model(engine: str, ram_mib: int, *, vram_mib: int = 0, inside_sandbox: bool = False):
    if ram_mib <= 0 or vram_mib < 0 or (inside_sandbox and vram_mib):
        raise ValueError("Réservation RAM/VRAM invalide.")
    with inference_lease():
        ram_limit = int(os.environ.get("AKASHA_RAM_LIMIT_MIB", DEFAULT_RAM_MIB))
        free_ram = available_ram()
        ram_available = ram_limit if inside_sandbox else min(ram_limit, free_ram)
        if ram_mib > ram_available:
            unavailable("ram_budget", requested_mib=ram_mib, available_mib=ram_available)
        free_vram = None
        if vram_mib:
            vram_limit = int(os.environ.get("AKASHA_VRAM_LIMIT_MIB", DEFAULT_VRAM_MIB))
            free_vram = available_vram()
            if vram_mib > min(vram_limit, free_vram):
                unavailable("vram_budget", requested_mib=vram_mib, available_mib=min(vram_limit, free_vram))
        admitted = perf_counter()
        record = {"engine": engine, "ram_reserved_mib": ram_mib, "vram_reserved_mib": vram_mib,
                  "inside_sandbox": inside_sandbox,
                  "host_ram_free_mib": free_ram, "device_vram_free_mib": free_vram}
        try:
            yield record
        finally:
            record["lease_s"] = round(perf_counter() - admitted, 3)
