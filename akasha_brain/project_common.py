"""Primitives partagées par le parcours projet et son résolveur."""

from hashlib import sha256
from pathlib import Path
import stat
from typing import NoReturn

from contracts.akasha_contracts.errors import AkashaError, ErrorCode


class ProjectError(RuntimeError):
    def __init__(self, error: AkashaError):
        super().__init__(error.message)
        self.error = error


def reject(code: ErrorCode, message: str, **details) -> NoReturn:
    raise ProjectError(AkashaError(code, message, details))


def digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def identity(project: Path) -> dict:
    info = project.stat()
    if not stat.S_ISDIR(info.st_mode):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Le projet doit être un dossier.")
    return {"path": str(project), "device": info.st_dev, "inode": info.st_ino}
