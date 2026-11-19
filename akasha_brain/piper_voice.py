"""Synthèse française sur CPU dans le bac hors ligne, lecture par l’application hôte."""

from base64 import b64decode
import ctypes
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
from uuid import uuid4
import wave
from zipfile import ZipFile

from bench.run_guided_repair import BENCH
from contracts.akasha_contracts.errors import ErrorCode
from .desktop_settings import app_directory
from .image_assets import PIPER_ARTIFACTS, matches
from .image_windows import PROBES, run_headless_guest, system32, tool_stdout
from .model_resources import reserve_model
from .notes_desktop import VC_RUNTIME
from .project_common import reject
from .specialist_registry import require_specialist
from .whisper_recovery import obtain

CAPABILITY = "audio.synthesize"
MAX_TEXT = 2000
RAM_MIB = 2048

# Ces sigles se prononcent lettre par lettre en français courant.
INITIALISMS = re.compile(r"\b(?:SNCF|TGV|RATP|RER|TVA|PDF|MCP|CPU|GPU|URL|TTC)\b")


def spoken_text(text):
    return INITIALISMS.sub(lambda found: " ".join(found[0]), " ".join(text.split()))


def validate_wav(data):
    with wave.open(BytesIO(data)) as stream:
        frames = stream.getnframes()
        if ((stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 22050)
                or not 1 <= frames <= 240*22050):
            raise ValueError("Format de la voix française invalide.")
        pcm = stream.readframes(frames)
        if len(pcm) != frames*2 or not any(pcm):
            raise ValueError("La voix n’a produit aucun son exploitable.")
        return frames/22050


def synthesize(text, checkpoint, *, ask=None, project=None):
    if not text.strip() or len(text) > MAX_TEXT or "\0" in text:
        raise ValueError(f"La lecture accepte de 1 à {MAX_TEXT} caractères par passage.")
    specialist = require_specialist(CAPABILITY, "audio", "fr-wav.v1", "piper-siwis-medium",
                                    ram_mib=RAM_MIB, fallback_authorized=True)
    cache = app_directory()/"piper-fr"
    if cache.resolve() != cache or (project and cache.is_relative_to(Path(project).resolve())):
        reject(ErrorCode.PERMISSION_DENIED, "La voix doit être installée dans le cache privé hors du projet.")
    cache.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    with TemporaryDirectory(prefix="akasha-piper-") as folder:
        stage = Path(folder)
        for item in PIPER_ARTIFACTS:
            checkpoint()
            if (cache/item.filename).resolve() != cache/item.filename or (cache/"approvals").resolve() != cache/"approvals":
                reject(ErrorCode.PERMISSION_DENIED, "Lien interdit dans le cache Piper.")
            path = obtain(cache, item, ask, checkpoint)
            target = stage/item.filename
            shutil.copyfile(path, target)
            if not matches(target, item):
                raise ValueError("Empreinte Piper incorrecte.")
        with ZipFile(stage/PIPER_ARTIFACTS[0].filename) as archive:
            archive.extractall(stage)
        (stage/PIPER_ARTIFACTS[0].filename).unlink()
        for filename in VC_RUNTIME:
            shutil.copyfile(system32()/filename, stage/"piper"/filename)
        for filename in (*PROBES, "piper_guest.ps1"):
            shutil.copyfile(BENCH/"harness"/filename, stage/filename)
        (stage/"reply.txt").write_text(spoken_text(text)+"\n", encoding="utf-8")

        def export(compute, mount):
            args = ("exec", compute, r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "-NoProfile",
                    "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", mount+r"\piper_guest.ps1")
            return tool_stdout("hcsdiag.exe", args, 15*1024**2, 90, checkpoint)

        with reserve_model(specialist.engine, RAM_MIB):
            proof, packet = run_headless_guest(stage, checkpoint, RAM_MIB, export)
        checkpoint()
        result = json.loads(packet)
        if "failure" in result:
            raise RuntimeError(f"Échec de la synthèse locale. {result}")
        data = b64decode(result["wav"], validate=True)
        return data, {"voice": specialist.id, "audio_s": validate_wav(data), "guest_peak_bytes": result["peak_bytes"],
                      "seconds_until_wav": perf_counter()-started, "sandbox_stopped": proof["sandbox_stopped"]}


def play_wav(data, checkpoint, on_start=lambda: None):
    """Un périphérique MCI par lecture permet l’arrêt sans couper une autre session."""
    send = ctypes.WinDLL("winmm", winmode=0x800).mciSendStringW
    send.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
    send.restype = ctypes.c_uint
    alias = "akasha"+uuid4().hex
    def command(value):
        buf = ctypes.create_unicode_buffer(64)
        if send(value, buf, len(buf), None):
            raise RuntimeError("La sortie audio Windows est indisponible.")
        return buf.value
    with TemporaryDirectory(prefix="akasha-lecture-") as tmp:
        path = Path(tmp)/"reponse.wav"
        path.write_bytes(data)
        checkpoint()
        command(f'open "{path}" type waveaudio alias {alias}')
        try:
            command("play "+alias)
            on_start()
            while command(f"status {alias} mode") == "playing":
                checkpoint()
                sleep(.04)
        finally:
            command("close "+alias)
