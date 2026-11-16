"""Nettoyage des matérialisations Notes après sortie ou interruption."""

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
from uuid import UUID

from .memory_store import MemoryRefusal


def run_folder(memory, run_id: str) -> Path:
    if str(UUID(run_id)) != run_id:
        raise ValueError("Identifiant d'exécution invalide.")
    root = memory.path.with_name(f"{memory.path.name}.scratch")
    folder = root / run_id
    if folder.resolve() != folder or not folder.is_relative_to(root):
        raise MemoryRefusal("erasure_pending", "Emplacement temporaire non vérifiable.")
    return folder


@contextmanager
def scratch_lease(folder: Path):
    import msvcrt

    lock = folder.with_suffix(".lock")
    if lock.resolve() != lock:
        raise MemoryRefusal("erasure_pending", "Verrou temporaire non vérifiable.")
    lock.parent.mkdir(parents=True, exist_ok=True)
    locked = False
    try:
        with lock.open("a+b") as stream:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise MemoryRefusal("erasure_pending", "Une exécution de la bibliothèque est en cours.") from error
            locked = True
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        if locked:
            lock.unlink(missing_ok=True)


def remove_run(folder: Path) -> None:
    if folder.exists():
        if folder.resolve() != folder:
            raise MemoryRefusal("erasure_pending", "Emplacement temporaire non vérifiable.")
        shutil.rmtree(folder)


def recover_scratch(memory, db, blocked: list[str]) -> None:
    if not blocked or not db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'memory_scratch'").fetchone():
        return
    runs = {row[0] for source in blocked for row in db.execute("SELECT run FROM memory_scratch WHERE source = ?", (source,))}
    for run_id in sorted(runs):
        try:
            folder = run_folder(memory, run_id)
            with scratch_lease(folder):
                path = folder / "run" / "report.json"
                if path.is_file():
                    report = json.loads(path.read_bytes())
                    sandbox = report.get("sandbox_id")
                    if sandbox and not report.get("sandbox_stopped"):
                        from .notes_sandbox import active_sandboxes

                        if str(UUID(sandbox)) in active_sandboxes():
                            raise MemoryRefusal("erasure_pending", "L'arrêt du bac de cette exécution reste à confirmer.")
                remove_run(folder)
            db.execute("DELETE FROM memory_scratch WHERE run = ?", (run_id,))
        except (OSError, ValueError, RuntimeError) as error:
            if isinstance(error, MemoryRefusal):
                raise
            raise MemoryRefusal("erasure_pending", "Le nettoyage d'une exécution de la bibliothèque est en attente.") from error
