"""Installe dans le bac les seules wheels approuvées préparées en lecture seule."""

from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def install(input_dir: Path, scratch: Path) -> None:
    request = json.loads((input_dir / "validation.json").read_bytes())
    requirements = scratch / "approved-wheels.txt"
    report = scratch / "installation.json"
    expected = set()
    lines = []
    for dependency in request["dependencies"]:
        wheel = input_dir / "wheels" / dependency["filename"]
        with wheel.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != dependency["sha256"]:
                raise RuntimeError("L'empreinte de la wheel diffère dans le bac.")
        url = wheel.as_uri()
        expected.add((normalized(dependency["name"]), dependency["version"], url))
        lines.append(f"{url} --hash=sha256:{dependency['sha256']}\n")
    requirements.write_text("".join(lines), encoding="utf-8")

    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
    env["PIP_CONFIG_FILE"] = os.devnull
    run_pip = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('pip',run_name='__main__')"
    subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-c", run_pip, str(input_dir / "installer"),
         "--isolated", "--disable-pip-version-check", "--no-cache-dir", "install", "--no-index", "--no-deps",
         "--require-hashes", "--no-compile", "--ignore-installed", "--target", str(scratch / "packages"),
         "--report", str(report), "--requirement", str(requirements)],
        env=env, check=True,
    )
    installed = json.loads(report.read_bytes())["install"]
    observed = {(normalized(entry["metadata"]["name"]), entry["metadata"]["version"], entry["download_info"]["url"])
                for entry in installed}
    if len(installed) != len(expected) or expected != observed:
        raise RuntimeError("Le rapport pip diffère des seules wheels approuvées.")


if __name__ == "__main__":
    install(Path(sys.argv[1]), Path(sys.argv[2]))
