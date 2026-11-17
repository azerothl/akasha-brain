"""Demandes d’accord et publication du PNG depuis la CLI."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import NamedTemporaryFile
from time import perf_counter

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .capability_recovery import Recovery
from .desktop_settings import app_directory, configured_runtime
from .image_assets import DownloadReview
from .image_recovery import CAPABILITY
from .planning import PlanningError
from .project_common import ProjectError, reject


def run_image(prompt: str, output: Path, runs: Path, runtime: Path | None = None) -> dict:
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 1500 or any(ord(char) < 32 and char not in "\t\n" for char in prompt):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Décrivez l’image souhaitée en 1 500 caractères au maximum.")
    output = output.parent.resolve() / output.name
    if output.suffix.lower() != ".png" or output.exists() or output.is_symlink() or not output.parent.is_dir():
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Indiquez un nouveau fichier PNG dans un dossier existant.")
    started = perf_counter()
    state = Recovery(runs.resolve() / "capability-recovery.sqlite", runtime or configured_runtime(),
                     lambda message: print(message, file=sys.stderr, flush=True), lambda: False)
    result = state.generate_image(prompt, None, None)
    while isinstance(result, DownloadReview):
        artifact = result.artifact
        print(f"Accord requis pour {artifact.name} ({artifact.size} octets)\n"
              f"Source {artifact.url}\nLicence {artifact.license} ({artifact.license_url})\n"
              f"SHA-256 {artifact.sha256}", file=sys.stderr, flush=True)
        if not sys.stdin.isatty():
            reject(ErrorCode.APPROVAL_REQUIRED, "Un terminal interactif est requis pour approuver cet artefact.")
        print("Autoriser ce téléchargement [oui/N] ?", end=" ", file=sys.stderr, flush=True)
        if sys.stdin.readline().strip().casefold() != "oui":
            reject(ErrorCode.APPROVAL_REQUIRED, "Téléchargement non autorisé.")
        result = state.generate_image(prompt, None, (result, result.approval_sha256))

    publish_png(output, result.png)
    active = state.stored(CAPABILITY)
    return {"status": "passed", "output": str(output), "validation": result.proof,
            "qualification": active[1], "wall_s": round(perf_counter() - started, 3)}


def publish_png(output: Path, png: bytes) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(prefix=".akasha-image-", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(png)
        os.link(temporary, output)
    except OSError:
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Le PNG n’a pas pu être publié à l’emplacement demandé.")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    cli = argparse.ArgumentParser(description="Générer et exporter un PNG depuis un bac local.")
    cli.add_argument("--prompt", required=True, help="Description de l’image")
    cli.add_argument("--output", required=True, type=Path, help="Nouveau fichier PNG")
    cli.add_argument("--runs", type=Path, default=app_directory() / "runs", help="Registre et cache des moteurs")
    cli.add_argument("--python-runtime", type=Path, help="Python portable pour Windows Sandbox")
    args = cli.parse_args()
    try:
        result = run_image(args.prompt, args.output, args.runs, args.python_runtime)
    except (ProjectError, PlanningError) as error:
        result = {"error": error.error.as_dict()}
    except (KeyboardInterrupt, InterruptedError):
        result = {"error": AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Demande annulée.").as_dict()}
    except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        result = {"error": AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, str(error)).as_dict()}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return int("error" in result)


if __name__ == "__main__":
    raise SystemExit(main())
