"""Vérifie l'état d'un fichier Windows sur le handle utilisé pour le supprimer."""

from contextlib import contextmanager
from hashlib import file_digest
import os
from pathlib import Path
import stat

from contracts.akasha_contracts.errors import ErrorCode

from .project_common import reject

GENERIC_READ = 0x80000000
DELETE_ACCESS = 0x00010000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_DISPOSITION_INFO = 4


def deletion_revision(info: os.stat_result) -> dict:
    if (not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        reject_stale_deletion()
    return {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
            "modified_ns": info.st_mtime_ns, "created_ns": getattr(info, "st_birthtime_ns", info.st_ctime_ns)}


def reject_stale_deletion() -> None:
    reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'état du fichier à supprimer a changé.",
           reason="project_changed", guard="transition", risk_class="R3")


@contextmanager
def deletion_handle(source: Path):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    close_file = kernel.CloseHandle
    close_file.argtypes = [wintypes.HANDLE]
    close_file.restype = wintypes.BOOL
    disposition = kernel.SetFileInformationByHandle
    disposition.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    disposition.restype = wintypes.BOOL

    # Exclut les écritures et les renommages concurrents durant la vérification.
    handle = open_file(str(source), GENERIC_READ | DELETE_ACCESS, FILE_SHARE_READ,
                       None, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        close_file(handle)
        raise

    def remove():
        delete_file = ctypes.c_ubyte(1)
        if not disposition(handle, FILE_DISPOSITION_INFO, ctypes.byref(delete_file), ctypes.sizeof(delete_file)):
            raise ctypes.WinError(ctypes.get_last_error())

    with os.fdopen(descriptor, "rb") as stream:
        yield stream, remove


@contextmanager
def verify_deletion(source: Path, expected_digest: str, expected_revision: dict):
    with deletion_handle(source) as (stream, remove):
        if (deletion_revision(os.fstat(stream.fileno())) != expected_revision
                or file_digest(stream, "sha256").hexdigest() != expected_digest):
            reject_stale_deletion()
        yield remove
