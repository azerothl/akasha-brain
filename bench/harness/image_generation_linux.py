"""Exécute sd-cli après vérification du bac Linux et transmet le PNG sur stdout."""

import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys

NAMESPACES = ("user", "mnt", "net", "pid")


def observe(host_namespaces):
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    interfaces = {line.split(":", 1)[0].strip() for line in Path("/proc/net/dev").read_text().splitlines()[2:]}
    read_only = ("/", "/usr/lib", "/engine", "/weights.gguf", "/request")
    return {
        "private_namespaces": all(os.readlink(f"/proc/self/ns/{kind}") != before
                                  for kind, before in zip(NAMESPACES, host_namespaces, strict=True)),
        "network_off": interfaces <= {"lo"},
        "read_only_input": all(os.statvfs(path).f_flag & os.ST_RDONLY for path in read_only),
        "private_scratch": any(row.split()[4] == "/work" and " - tmpfs " in row
                               for row in Path("/proc/self/mountinfo").read_text().splitlines()),
        "no_privileges": status["NoNewPrivs"].strip() == "1" and int(status["CapEff"], 16) == 0,
        "headless": not any(name in os.environ for name in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")),
    }


def main():
    memory, byte_limit = map(int, sys.argv[1:3])
    controls = observe(sys.argv[3:])
    print(json.dumps(controls), flush=True)
    if not all(controls.values()) or sys.stdin.buffer.read(1) != b"+":
        return 2
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (byte_limit, byte_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    target = Path("/work/result.png")
    prompt = Path("/request/prompt.txt").read_text(encoding="utf-8")
    result = subprocess.run([
        "/engine/sd-cli", "-m", "/weights.gguf", "-p", prompt,
        "--steps", "4", "--cfg-scale", "1.0", "--sampling-method", "euler_a",
        "-W", "512", "-H", "512", "-t", "8", "--seed", "3927", "-o", str(target),
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=540)
    if result.returncode:
        return 3
    with os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as data:
        info = os.fstat(data.fileno())
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= byte_limit:
            return 4
        contents = data.read(byte_limit + 1)
        if len(contents) != info.st_size:
            return 4
    sys.stdout.buffer.write(contents)
    return 0


if __name__ == "__main__":
    sys.exit(main())
