"""Exercise the real isolated subprocess/PCM transport with a CPU-only synthesizer."""

import ctypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from threading import Event, Lock, get_ident
from time import monotonic, sleep
import venv

import pytest

from akasha_brain import model_resources, qwen_resident as resident, qwen_voice_worker as worker


@pytest.fixture(scope="module")
def interpreter(tmp_path_factory):
    env = tmp_path_factory.mktemp("vivian-python") / "env"
    venv.EnvBuilder(with_pip=False).create(env)
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


@pytest.fixture
def voice(tmp_path, interpreter, monkeypatch):
    import shutil

    home = tmp_path / "runtime"
    scripts = home / "env/Scripts"
    scripts.mkdir(parents=True)
    if os.name == "nt":
        shutil.copy(interpreter, scripts / "python.exe")
        shutil.copy(interpreter.parents[1] / "pyvenv.cfg", scripts.parent)
    else:
        (scripts / "python.exe").symlink_to(interpreter)
    fake = tmp_path / "synthesis.py"
    fake.write_text(f"""
import importlib.util, os, sys, time, socket
from pathlib import Path
spec = importlib.util.spec_from_file_location("voice_worker", {str(resident.WORKER)!r})
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
def load(home):
    assert sys.flags.isolated and Path.cwd() == home
    assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
    print("library output on stdout", flush=True)
    with (home / "loads").open("a") as log:
        print(os.getpid(), file=log)
    if (home / "stall").exists():
        time.sleep(30)
    def generate(text, prompt):
        if text in ("stale", "oversize", "odd"):
            def invalid(out, kind, request, payload=b""):
                if kind == b"P":
                    size = w.MAX_FRAME + 1 if text == "oversize" else 1
                    out.write(w.HEADER.pack(kind, request + int(text == "stale"), size))
                    out.write(b"x")
                    out.flush()
            w.send = invalid
        if text == "network":
            socket.getaddrinfo("example.invalid", 443)
        if text == "hang":
            (home / "generating").touch()
            time.sleep(30)
        if text == "empty":
            return
        if text == "fail":
            yield b"ok"
            raise RuntimeError("failed after audio")
        yield text.encode("utf-16le")
        yield prompt.encode("utf-16le")
    return generate
w.load_synthesizer = load
w.main()
""", encoding="utf-8")
    monkeypatch.setenv("AKASHA_QWEN_HOME", str(home))
    for resource in ("RAM", "VRAM"):
        monkeypatch.setenv(f"AKASHA_{resource}_LIMIT_MIB", "8192")
    monkeypatch.setattr(model_resources, "available_ram", lambda: 8192)
    monkeypatch.setattr(model_resources, "available_vram", lambda: 8192)
    lease = Lock()
    @contextmanager
    def private_lease():
        if not lease.acquire(blocking=False):
            model_resources.unavailable("inference_busy")
        try:
            yield
        finally:
            lease.release()
    monkeypatch.setattr(model_resources, "inference_lease", private_lease)
    monkeypatch.setattr(resident, "WORKER", fake)
    voice = resident.ResidentVoice()
    yield voice
    voice.close()


def collect(voice, text="Bonjour", style="reference"):
    blocks = []
    voice.stream(text, style, lambda: None, blocks.append)
    return blocks


def alive(pid):
    if os.name == "nt":
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.restype = wintypes.HANDLE
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(wintypes.HANDLE(handle), 0) == 0x102
        finally:
            api.CloseHandle(wintypes.HANDLE(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_until(condition):
    limit = monotonic() + 5
    while not condition() and monotonic() < limit:
        sleep(.02)
    assert condition()


def test_stream_warm_stop_and_resume_same_loaded_worker(voice):
    assert collect(voice) == ["Bonjour".encode("utf-16le"), resident.STYLES["reference"].encode("utf-16le")]
    pid = voice.pid
    assert alive(pid)
    emitter = get_ident()
    blocks = []

    def checkpoint():
        assert get_ident() == emitter
        if blocks:
            raise InterruptedError("stop")

    def emit(data):
        assert get_ident() == emitter
        blocks.append(data)

    with pytest.raises(InterruptedError, match="stop"):
        voice.stream("Ancien", "reference", checkpoint, emit)
    assert blocks == ["Ancien".encode("utf-16le")]
    assert voice.pid == pid
    assert collect(voice, "Nouveau", "sobre") == [
        "Nouveau".encode("utf-16le"), resident.STYLES["sobre"].encode("utf-16le")]
    assert (resident.runtime_home() / "loads").read_text().splitlines() == [str(pid)]
    voice.close()
    voice.close()
    wait_until(lambda: not alive(pid))
    assert voice.pid is None


@pytest.mark.parametrize("warm", [False, True])
def test_stop_during_stalled_load_or_generation_reaps_worker(voice, warm):
    home = resident.runtime_home()
    if warm:
        collect(voice)
        started = home / "generating"
    else:
        (home / "stall").touch()
        started = home / "loads"
    pids = []
    deadline = monotonic() + 5

    def checkpoint():
        assert monotonic() < deadline
        if started.exists() and voice.pid:
            pids.append(voice.pid)
            raise InterruptedError("stop")

    with pytest.raises(InterruptedError, match="stop"):
        voice.stream("hang", "sobre", checkpoint, lambda _: pytest.fail("stale audio"))
    wait_until(lambda: not alive(pids[0]))
    assert voice.pid is None
    (home / "stall").unlink(missing_ok=True)
    assert collect(voice)[0] == "Bonjour".encode("utf-16le")


@pytest.mark.parametrize("error", [OSError("audio device"), ValueError("audio buffer")])
def test_sink_exception_identity(voice, error):
    def fail(_):
        raise error
    with pytest.raises(type(error)) as seen:
        voice.stream("test", "sobre", lambda: None, fail)
    assert seen.value is error
    assert voice.pid is None


def test_admission_cold_warm_budget_and_concurrency(voice, monkeypatch):
    free = 1024
    monkeypatch.setattr(model_resources, "available_vram", lambda: free)
    with pytest.raises(resident.QwenUnavailable) as cold:
        collect(voice)
    assert cold.value.reason == "vram_budget"
    assert not (resident.runtime_home() / "loads").exists()
    free = 8192
    collect(voice)
    pid = voice.pid
    free = 1024  # resident weights are already charged
    observed = []
    def while_speaking(block):
        with pytest.raises(resident.QwenUnavailable) as busy:
            collect(voice)
        assert busy.value.reason == "inference_busy"
        with pytest.raises(model_resources.PlanningError) as other_engine:
            with model_resources.inference_lease():
                pytest.fail("overlapping inference")
        assert other_engine.value.error.details["reason"] == "inference_busy"
        observed.append(block)
    voice.stream("oui", "sobre", lambda: None, while_speaking)
    assert len(observed) == 2 and voice.pid == pid
    monkeypatch.setenv("AKASHA_VRAM_LIMIT_MIB", "2048")
    with pytest.raises(resident.QwenUnavailable) as capped:
        collect(voice)
    assert capped.value.reason == "vram_budget"
    assert voice.pid is None


def test_missing_gpu_and_pre_vs_post_audio_errors(voice, monkeypatch):
    def absent():
        model_resources.unavailable("cuda_device_unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(model_resources, "available_vram", absent)
        with pytest.raises(resident.QwenUnavailable) as seen:
            collect(voice)
        assert seen.value.reason == "cuda_device_unavailable"
    for text, reason in [("empty", "empty_audio"), ("network", "PermissionError")]:
        with pytest.raises(resident.QwenUnavailable) as seen:
            collect(voice, text)
        assert seen.value.reason == reason
    blocks = []
    with pytest.raises(RuntimeError) as seen:
        voice.stream("fail", "reference", lambda: None, blocks.append)
    assert not isinstance(seen.value, resident.QwenUnavailable)
    assert blocks == [b"ok"]


def test_idle_releases_worker(voice, monkeypatch):
    monkeypatch.setattr(resident, "IDLE_SECONDS", .15)
    collect(voice)
    pid = voice.pid
    wait_until(lambda: voice.pid is None)
    wait_until(lambda: not alive(pid))


@pytest.mark.parametrize("text,reason", [("stale", "invalid_frame"), ("oversize", "invalid_frame"),
                                         ("odd", "invalid_pcm")])
def test_invalid_frame_rejected_before_delivery(voice, text, reason):
    with pytest.raises(resident.QwenUnavailable) as seen:
        voice.stream(text, "reference", lambda: None, lambda _: pytest.fail("invalid PCM delivered"))
    assert seen.value.reason == reason
    assert voice.pid is None
    assert collect(voice, "ok")[0] == "ok".encode("utf-16le")


def test_checkpoint_can_cancel_pending_resource_probe(voice, monkeypatch):
    measuring, release, finished = Event(), Event(), Event()
    @contextmanager
    def delayed_admission(*args, **kwargs):
        measuring.set()
        try:
            assert release.wait(5)
            yield
        finally:
            finished.set()
    monkeypatch.setattr(resident, "reserve_model", delayed_admission)
    emitter = get_ident()
    def checkpoint():
        assert get_ident() == emitter
        if measuring.is_set():
            raise InterruptedError("stop")
    try:
        with pytest.raises(InterruptedError, match="stop"):
            voice.stream("test", "sobre", checkpoint, lambda _: pytest.fail("unexpected PCM"))
    finally:
        release.set()
    assert finished.wait(5)
    assert voice.pid is None and not (resident.runtime_home() / "loads").exists()


def test_settings_and_invalid_passage(voice, tmp_path, monkeypatch):
    home = resident.runtime_home()
    monkeypatch.delenv("AKASHA_QWEN_HOME")
    monkeypatch.setattr(resident, "app_directory", lambda: tmp_path)
    (tmp_path / "qwen-voice-home.txt").write_text(str(home), encoding="utf-8-sig")
    assert resident.runtime_home() == home
    for value in ["", "x" * 221, "a\0b"]:
        with pytest.raises(ValueError):
            collect(voice, value)
    monkeypatch.setenv("AKASHA_QWEN_HOME", "relative")
    with pytest.raises(resident.QwenUnavailable) as seen:
        collect(voice)
    assert seen.value.reason == "runtime_path"


def test_pins_match_benchmark_and_cache_cannot_authorize_changes(tmp_path):
    report = Path(__file__).resolve().parents[1] / "bench/results/g8-prosodie-79ee9ff269b9-latences.json"
    model = json.loads(report.read_bytes())["profiles"]["qwen"]["model"]
    assert worker.REVISION == model["revision"]
    assert worker.FILES == {key: item["sha256"] for key, item in model["files"].items()}
    path = tmp_path / "models" / worker.REVISION
    path.mkdir(parents=True)
    (path / "config.json").write_bytes(b"{}")
    (path / "hub-metadata.json").write_text('{"siblings":[]}')
    with pytest.raises(worker.WorkerFailure, match="model_integrity"):
        worker.verify_model(tmp_path)


def test_native_pcm_format_and_bounds():
    import numpy as np
    assert worker.pcm16(np.array([-2, -.5, 0, .5, 1]), 24000) == struct.pack("<5h", -32768, -16384, 0, 16384, 32767)
    for data, rate in [([1], 16000), ([[0, 0]], 24000), ([float("nan")], 24000)]:
        with pytest.raises(worker.WorkerFailure):
            worker.pcm16(data, rate)


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop Job Object")
def test_abrupt_desktop_exit_releases_real_worker(voice):
    code = """
import os, sys
from contextlib import nullcontext
from pathlib import Path
from akasha_brain import qwen_resident as q, model_resources as r
r.available_vram = r.available_ram = lambda: 8192
r.inference_lease = nullcontext
q.WORKER = Path(sys.argv[1])
q.VOICE.stream("test", "sobre", lambda: None, lambda _: None)
print(q.VOICE.pid, flush=True)
os._exit(0)
"""
    pid = int(subprocess.check_output([sys.executable, "-c", code, str(resident.WORKER)], timeout=10))
    wait_until(lambda: not alive(pid))
