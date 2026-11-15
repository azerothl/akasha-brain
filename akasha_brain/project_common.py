"""Primitives partagées par le parcours projet et son résolveur."""

from hashlib import sha256
import json
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


def project_scope(project: Path) -> str:
    """Identifiant d'accord lié au dossier effectivement ouvert."""
    record = identity(project.resolve(strict=True))
    return "local-project:" + digest(json.dumps(record, sort_keys=True).encode("utf-8"))
