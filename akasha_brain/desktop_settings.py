"""Configuration locale du lanceur Windows."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def app_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AkashaBrain"


def configured_runtime() -> Path | None:
    directory = app_directory()
    try:
        saved = Path((directory / "python-runtime.txt").read_text(encoding="utf-8-sig").strip())
    except (OSError, UnicodeError):
        saved = None
    default = directory / "python-portable-3.12.7"
    return next((path for path in (saved, default)
                 if path is not None and path.is_absolute() and (path / "python.exe").is_file()), None)


def remember_runtime(runtime: Path) -> None:
    directory = app_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
        draft = Path(stream.name)
        stream.write(str(runtime.resolve()) + "\n")
    try:
        draft.replace(directory / "python-runtime.txt")
    finally:
        draft.unlink(missing_ok=True)
