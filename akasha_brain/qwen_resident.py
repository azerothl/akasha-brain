"""Vivian résidente. Un crédit par bloc PCM, un seul passage admis à la fois."""

import atexit
from contextlib import suppress
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from queue import Empty, Queue
import struct
import subprocess
from threading import Event, Lock, Thread, Timer, current_thread
from time import monotonic
from uuid import uuid4

from . import qwen_voice_worker as wire
from .desktop_settings import app_directory
from .model_resources import DEFAULT_RAM_MIB, DEFAULT_VRAM_MIB, reserve_model
from .planning import PlanningError
from .specialist_registry import require_specialist
from .voice_style import STYLES


ENGINE = "faster-qwen3-tts"
RAM_MIB = VRAM_MIB = 6144
WARM_HEADROOM_MIB = 512
WORKER = Path(wire.__file__).resolve()
IDLE_SECONDS = 120
STOP_GRACE = 0.8
POLL = 0.025


class QwenUnavailable(RuntimeError):
    """Fallback is possible before the first PCM callback."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"Voix Vivian indisponible ({reason}).")


def runtime_home():
    value = os.environ.get("AKASHA_QWEN_HOME")
    if value is None:
        try:
            value = (app_directory() / "qwen-voice-home.txt").read_text("utf-8-sig").strip()
        except (OSError, UnicodeError) as error:
            raise QwenUnavailable("runtime_unconfigured") from error
    home = Path(value)
    if not home.is_absolute() or home.anchor.startswith(("\\\\", "//")):
        raise QwenUnavailable("runtime_path")
    if not (home / "env/Scripts/python.exe").is_file():
        raise QwenUnavailable("runtime_missing")
    return home.resolve(strict=True)


def create_job(name):
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION, including the pointer-sized fields on Win64.
    class Limits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Limits), ("io_counters", ctypes.c_uint64 * 6),
                    ("memory_limits_and_peaks", ctypes.c_size_t * 4)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = api.CreateJobObjectW(None, name)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended(basic=Limits(flags=0x2000))  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.WinError(ctypes.get_last_error())
        api.CloseHandle(job)
        raise error
    return lambda: api.CloseHandle(job)


class Worker:
    def __init__(self, home):
        self.home = home
        self.pid = None
        job_name = "Local\\AkashaVivian-" + uuid4().hex
        self.close_job = create_job(job_name) if os.name == "nt" else None
        environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                           HF_HUB_DISABLE_TELEMETRY="1", GRADIO_ANALYTICS_ENABLED="False",
                           HF_HOME=str(home / "hf"), NUMBA_CACHE_DIR=str(home / "numba"),
                           CUDA_CACHE_PATH=str(home / "cuda-cache"))
        try:
            self.process = subprocess.Popen(
                [str(home / "env/Scripts/python.exe"), "-I", "-u", str(WORKER), str(home), job_name],
                cwd=home, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except BaseException:
            if self.close_job:
                self.close_job()
            raise

    def close(self):
        if self.close_job:
            self.close_job()
        self.process.kill()
        self.process.wait()
        with suppress(BrokenPipeError):
            self.process.stdin.close()
        self.process.stdout.close()

    def write(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def frame(self, expected):
        pipe = self.process.stdout
        header = pipe.read(wire.HEADER.size)
        if len(header) != wire.HEADER.size:
            raise QwenUnavailable("worker_exit")
        kind, request, size = wire.HEADER.unpack(header)
        if request != expected or size > wire.MAX_FRAME:
            raise QwenUnavailable("invalid_frame")
        data = pipe.read(size)
        if len(data) != size:
            raise QwenUnavailable("truncated_frame")
        if kind == b"E":
            raise QwenUnavailable(data[:128].decode("ascii", "replace"))
        return kind, data


@dataclass
class Request:
    number: int
    stop: Event = field(default_factory=Event)
    credit: Event = field(default_factory=Event)
    reusable: Event = field(default_factory=Event)
    warm: Event = field(default_factory=Event)
    events: Queue = field(default_factory=lambda: Queue(maxsize=2))

    def interrupt(self):
        self.stop.set()
        self.credit.set()


class ResidentVoice:
    def __init__(self):
        self._lock = Lock()
        self._worker = None
        self._active = None
        self._idle = None
        self._sequence = 0

    @property
    def pid(self):
        with self._lock:
            if self._worker and self._worker.process.poll() is None:
                return self._worker.pid
            return None

    def _discard(self):
        if self._worker is not None:
            self._worker.close()
            self._worker = None

    def _expire(self):
        with self._lock:
            if self._idle is current_thread():
                self._idle = None
                self._discard()

    def close(self):
        with self._lock:
            if self._idle:
                self._idle.cancel()
                self._idle = None
            if self._active:
                self._active.interrupt()
            self._discard()

    def _exchange(self, call, command):
        specialist = require_specialist("audio.synthesize", "audio", "fr-pcm-stream.v1", ENGINE, ram_mib=RAM_MIB)
        home = runtime_home()
        with self._lock:
            if call.stop.is_set():
                return
            if self._worker and (self._worker.home != home or self._worker.process.poll() is not None):
                self._discard()
            warm = self._worker is not None
            if warm:
                call.warm.set()

        # Existing weights already count against free memory. The configured caps still
        # cover the whole model, while only incremental headroom must be free on warm calls.
        if warm and int(os.environ.get("AKASHA_RAM_LIMIT_MIB", DEFAULT_RAM_MIB)) < RAM_MIB:
            raise QwenUnavailable("ram_budget")
        if warm and int(os.environ.get("AKASHA_VRAM_LIMIT_MIB", DEFAULT_VRAM_MIB)) < VRAM_MIB:
            raise QwenUnavailable("vram_budget")
        ram = WARM_HEADROOM_MIB if warm else specialist.ram_mib
        vram = WARM_HEADROOM_MIB if warm else VRAM_MIB
        with reserve_model(ENGINE, ram, vram_mib=vram):
            with self._lock:
                if call.stop.is_set():
                    return
                if self._worker is None:
                    self._worker = Worker(home)
                worker = self._worker
            if not warm:
                kind, data = worker.frame(0)
                if kind != b"R" or len(data) != 4:
                    raise QwenUnavailable("invalid_handshake")
                worker.pid, = struct.unpack("!I", data)
            worker.write(command)
            total = 0
            while True:
                kind, data = worker.frame(call.number)
                completed = kind == b"D" and total > 0
                stopped = kind == b"S" and call.stop.is_set()
                if not data and (completed or stopped):
                    call.reusable.set()
                    return
                total += len(data)
                if kind != b"P" or not data or len(data) % 2 or total > wire.MAX_PCM:
                    raise QwenUnavailable("invalid_pcm")
                call.warm.set()
                call.credit.clear()
                if not call.stop.is_set():
                    call.events.put(data)
                    call.credit.wait()
                worker.write(b"-\n" if call.stop.is_set() else b"+\n")

    def _run(self, call, command):
        try:
            self._exchange(call, command)
        except PlanningError as error:
            call.events.put(QwenUnavailable((error.error.details or {}).get("reason", error.error.code.value)))
        except QwenUnavailable as error:
            call.events.put(error)
        except Exception as error:
            call.events.put(QwenUnavailable(type(error).__name__))
        else:
            call.events.put(None)

    def stream(self, text, style, checkpoint, on_pcm):
        if not isinstance(text, str) or not text.strip() or len(text) > wire.MAX_TEXT or "\0" in text:
            raise ValueError("La voix Vivian accepte de 1 à 220 caractères par passage.")
        prompt = STYLES[style]
        checkpoint()
        with self._lock:
            if self._active is not None:
                raise QwenUnavailable("inference_busy")
            self._sequence = self._sequence % 0xffffffff + 1
            call = Request(self._sequence)
            command = json.dumps([call.number, text, prompt], ensure_ascii=False).encode("utf-8") + b"\n"
            if len(command) > wire.MAX_REQUEST:
                raise ValueError("Passage trop volumineux.")
            if self._idle:
                self._idle.cancel()
                self._idle = None
            self._active = call
        thread = Thread(target=self._run, args=(call, command), name="Vivian PCM", daemon=True)
        spoke = False
        keep = False
        try:
            thread.start()
            deadline = monotonic() + 180
            while True:
                checkpoint()
                if call.stop.is_set():
                    raise InterruptedError("Lecture arrêtée.")
                if monotonic() >= deadline:
                    if spoke:
                        raise RuntimeError("Délai de réponse de Vivian dépassé.")
                    raise QwenUnavailable("worker_timeout")
                try:
                    event = call.events.get(timeout=POLL)
                except Empty:
                    continue
                checkpoint()
                if call.stop.is_set():
                    raise InterruptedError("Lecture arrêtée.")
                if event is None:
                    keep = True
                    return
                if isinstance(event, QwenUnavailable):
                    if spoke:
                        raise RuntimeError(f"Lecture Vivian interrompue ({event.reason}).") from event
                    raise event
                spoke = True
                on_pcm(event)
                checkpoint()
                call.credit.set()
        except InterruptedError:
            call.interrupt()
            if call.warm.is_set():
                thread.join(STOP_GRACE)
                keep = call.reusable.is_set()
            raise
        finally:
            call.interrupt()
            with self._lock:
                if not keep:
                    self._discard()
                elif self._worker:
                    self._idle = Timer(IDLE_SECONDS, self._expire)
                    self._idle.daemon = True
                    self._idle.start()
                self._active = None


VOICE = ResidentVoice()
atexit.register(VOICE.close)
