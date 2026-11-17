"""Génère dans Windows Sandbox et écrit une enveloppe PNG sur stdout."""

from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    root = Path(__file__).parent
    byte_limit = int(sys.argv[1])
    prompt = (root / "image-prompt.txt").read_text(encoding="utf-8")
    with TemporaryDirectory(prefix="akasha-image-") as directory:
        work = Path(directory)
        engine = work / "engine"
        shutil.copytree(root / "engine", engine)
        target = work / "result.png"
        result = subprocess.run([
            str(engine / "sd-cli.exe"), "-m", str(root / "image-model.gguf"), "-p", prompt,
            "--steps", "4", "--cfg-scale", "1.0", "--sampling-method", "euler_a",
            "-W", "512", "-H", "512", "-t", "8", "--seed", "3927", "-o", str(target),
        ], cwd=engine, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=540, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            return 3
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or not 1 <= info.st_size <= byte_limit):
            return 4
        with target.open("rb") as stream:
            raw = stream.read(byte_limit + 1)
        if len(raw) != info.st_size:
            return 4
        packet = {"bytes": len(raw), "sha256": sha256(raw).hexdigest(), "data": b64encode(raw).decode("ascii")}
        print(json.dumps(packet, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
