"""Serveur Rbitnet local à durée de vie bornée pour les essais et le desktop."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .model_resources import DEFAULT_RAM_MIB, DEFAULT_VRAM_MIB, reserve_model
from .planning import PlanningError


class Session:
    def __init__(self, port, startup_s, metadata):
        self.endpoint = f"http://127.0.0.1:{port}"
        self.http = build_opener(ProxyHandler({}))
        self.startup_s = startup_s
        self.metadata = metadata

    def request(self, route, data=None, *, timeout=5):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        request = Request(self.endpoint + route, data=payload, headers={"Content-Type": "application/json"})
        with self.http.open(request, timeout=timeout) as response:
            return response.read().decode("utf-8")

    def chat(self, messages, *, seed, max_tokens, stop, timeout):
        started = perf_counter()
        result = json.loads(self.request("/v1/chat/completions", {
            "model": self.metadata["id"], "messages": messages, "max_tokens": max_tokens,
            "temperature": 0.0, "seed": seed, "stop": stop, "stream": False,
        }, timeout=timeout))
        return result, round(perf_counter() - started, 3)


@contextmanager
def server(paths, work: Path, *, backend="cpu", cuda_library=None, threads=8, ram_mib=DEFAULT_RAM_MIB,
           vram_mib=DEFAULT_VRAM_MIB, template=None):
    if backend not in ("cpu", "cuda") or (backend == "cuda" and (cuda_library is None or vram_mib <= 0)):
        raise ValueError("Le backend demande une configuration CPU ou une bibliothèque CUDA locale.")
    requested_vram = vram_mib if backend == "cuda" else 0
    with reserve_model("rbitnet", ram_mib, vram_mib=requested_vram) as residency:
        with _serve(paths, work, backend, cuda_library, threads, ram_mib, requested_vram, template) as instance:
            instance.residency = residency
            yield instance


@contextmanager
def _serve(paths, work, backend, cuda_library, threads, ram_mib, vram_mib, template):
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    config = work / "rbitnet.toml"
    config.touch()
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("RBITNET_")}
    env.update(RBITNET_BIND=f"127.0.0.1:{port}", RBITNET_BACKEND=backend, RBITNET_MODEL=str(paths.model),
               RBITNET_TOKENIZER=str(paths.tokenizer), RBITNET_CONFIG=str(config.resolve()),
               RBITNET_REQUIRE_MODEL_MATCH="1", RBITNET_CHAT_FORMAT="chatml", RUST_LOG="info",
               HF_HUB_OFFLINE="1", RAYON_NUM_THREADS=str(threads), RBITNET_I2S_THREADS=str(threads),
               RBITNET_I2S_BATCH_THREADS=str(threads), RBITNET_MAX_LOAD_BYTES=str(ram_mib * 1024 * 1024))
    if cuda_library is not None and backend == "cuda":
        env.update(RBITNET_CUDA_QUANT_LIB=str(cuda_library), RBITNET_MAX_VRAM_MB=str(vram_mib), CUDA_VISIBLE_DEVICES="0")
    if template is not None:
        env["RBITNET_CHAT_TEMPLATE"] = template
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log_path = work / "rbitnet.log"
    with log_path.open("wb") as log:
        started = perf_counter()
        try:
            process = subprocess.Popen([str(paths.engine)], cwd=work, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as error:
            raise PlanningError(AkashaError(ErrorCode.CAPABILITY_UNAVAILABLE, "Rbitnet ne démarre pas.")) from error
        instance = Session(port, None, None)

        def load_error(message):
            local_log = log_path.read_text(encoding="utf-8", errors="replace")
            if any(f"exceeds {key}" in local_log for key in ("RBITNET_MAX_LOAD_BYTES", "RBITNET_MAX_VRAM_MB")):
                return PlanningError(AkashaError(ErrorCode.RESIDENCY_UNAVAILABLE, "Rbitnet refuse le budget de mémoire."))
            return PlanningError(AkashaError(ErrorCode.CAPABILITY_UNAVAILABLE, message))

        try:
            while process.poll() is None and perf_counter() - started < 25:
                try:
                    instance.request("/ready", timeout=2)
                    break
                except HTTPError as error:
                    problem = error.read().decode("utf-8", errors="replace")
                    if "LoadFailed" in problem:
                        raise load_error("Rbitnet a refusé le chargement local. Voir rbitnet.log.") from error
                except (OSError, URLError):
                    pass
                sleep(0.15)
            else:
                raise load_error("Rbitnet indisponible. Voir rbitnet.log.")
            instance.startup_s = round(perf_counter() - started, 3)
            instance.metadata = json.loads(instance.request("/v1/models"))["data"][0]
            yield instance
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=8)
