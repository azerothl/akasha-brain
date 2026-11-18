"""Pilote français Windows. Le cache et le modèle sont choisis par l’hôte."""

from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import wave

from bench.run_guided_repair import BENCH, file_hash
from contracts.akasha_contracts.errors import ErrorCode
from .desktop_settings import app_directory
from .image_windows import PROBES, run_headless_guest, system32, tool_stdout
from .model_resources import reserve_model
from .notes_desktop import VC_RUNTIME
from .project import project_file, project_input
from .project_common import project_scope, reject
from .specialist_registry import require_specialist
from .planning import PlanningError
from . import whisper_recovery, whisper_resident

CAPABILITY = "audio.transcribe"
MANIFEST = {"capability_id": CAPABILITY, "version": "1.0.0", "kind": "adapter",
            "description": "Transcrire en français un WAV ou FLAC local. Signaler les segments à vérifier.",
            "permissions": {"reads": ["selected-project"], "writes": ["sandbox-scratch"], "execute": ["whisper-cuda", "whisper-cpu"]},
            "risk_class": "R1", "sandbox": {"tier": "windows-sandbox", "network_egress": False},
            "side_effects": "local-temporary"}
HASHES = {
    "ggml-small.bin": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    "whisper-cli.exe": "0ff971e410240a0b97117432d771245698f376e06105c011959d2bfc4bb23311",
    "ggml-base.dll": "61c9c57f49f380896ed54ed3f71735e10a2d986f482c2b0a55e72b47f731b193",
    "ggml-cpu.dll": "eb2f1d023e51c40b27463b5ab165600eb48cb60323740f400b1b62e1c8706c56",
    "ggml.dll": "bcfeaf6e5b59c315fc36e290715aa7a84b22461e968543c13dfcf57df7b1b81d",
    "whisper.dll": "4037a6567fbb08fc7efda18e4d128a95df9c31ba171af20439d1a93b785d007e",
    "SDL2.dll": "de23db1694a3c7a4a735e7ecd3d214b2023cc2267922c6c35d30c7fc7370d677"}
RAM_MIB = 4096


def cache_path():
    if os.name != "nt":
        return None
    value = os.environ.get("AKASHA_WHISPER_CACHE")
    if value is None:
        try:
            value = (app_directory()/"whisper-cache.txt").read_text("utf-8-sig").strip()
        except FileNotFoundError:
            return app_directory()/"whisper-small"
        except (OSError, UnicodeError):
            return None
    return Path(value) if value and Path(value).is_absolute() else None


def configured():
    return cache_path() is not None


def audio_info(raw, suffix):
    message = "Le pilote accepte WAV PCM16 ou FLAC mono 16 kHz sur 16 bits, de 1 ms à 2 minutes."
    if suffix == ".wav":
        try:
            with wave.open(BytesIO(raw)) as stream:
                frames = stream.getnframes()
                valid = (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (1, 2, 16000)
                pcm = stream.readframes(frames)
                valid = valid and len(pcm) == frames * 2
        except (EOFError, wave.Error, OverflowError):
            valid, frames = False, 0
        silent = valid and not any(pcm)
    elif suffix == ".flac" and raw.startswith(b"fLaC") and len(raw) >= 42 and raw[4] & 127 == 0 and raw[5:8] == b"\0\0\x22":
        info = int.from_bytes(raw[18:26], "big")
        frames = info & ((1 << 36) - 1)
        valid = (info >> 44, (info >> 41) & 7, (info >> 36) & 31) == (16000, 0, 15)
        silent = False
    else:
        valid, frames, silent = False, 0, False
    if not valid or not 16 <= frames <= 120 * 16000:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, message)
    return round(frames / 16), silent


def server_segment(segment):
    tokens = [{"id": ident, "text": word["word"], "p": word["probability"]}
              for ident, word in zip(segment.get("tokens", []), segment.get("words", []), strict=True)]
    return {"text": segment["text"], "offsets": {"from": round(segment["start"]*1000),
            "to": round(segment["end"]*1000)}, "tokens": tokens}


def decode(raw, duration, *, server=False):
    segments = []
    try:
        response = json.loads(raw.decode("utf-8", errors="replace"))
        items = (server_segment(s) for s in response["segments"]) if server else response["transcription"]
        for item in items:
            text = item["text"].strip()
            if not any(c.isalnum() for c in text) or text == "[BLANK_AUDIO]":
                continue
            start, end = (item["offsets"][k] for k in ("from", "to"))
            if type(start) is not int or type(end) is not int or not 0 <= start < end or start >= duration:
                raise ValueError
            if segments and start < segments[-1]["end_ms"]:
                raise ValueError
            tokens = [t["p"] for t in item["tokens"] if 0 <= t["id"] < 50257 and any(c.isalnum() for c in t["text"])]
            if any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1 for p in tokens):
                raise ValueError
            reasons = []
            if not tokens:
                reasons.append("missing_scores")
            elif min(tokens) < .50 or sum(tokens)/len(tokens) < .80:
                reasons.append("low_token_confidence")
            if end > duration:
                reasons.append("timestamp_clipped")
            if "\ufffd" in text:
                reasons.append("invalid_text_encoding")
            segments.append({"start_ms": start, "end_ms": min(end, duration), "text": text,
                             "uncertain": bool(reasons), "reasons": reasons,
                             "min_token_p": round(min(tokens), 3) if tokens else None})
    except (TypeError, ValueError, OverflowError, KeyError, AttributeError):
        reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Segments ou scores Whisper invalides.")
    return segments


def transcribe(project, name, checkpoint=lambda: None, *, ask=None, progress=lambda _: None):
    specialist = require_specialist(CAPABILITY, "audio", "fr-transcript.v1", "whisper.cpp-small", ram_mib=RAM_MIB)
    cache = cache_path()
    if cache is None:
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Configurez le cache local du pilote Whisper.")
    project = project.resolve(strict=True)
    scope = project_scope(project)
    if cache.resolve() != cache or cache.is_relative_to(project) or project.is_relative_to(cache):
        reject(ErrorCode.PERMISSION_DENIED, "Le cache du spécialiste doit être hors du projet.")
    path = project_file(project, name)
    suffix = path.suffix.lower()
    if suffix not in {".wav", ".flac"}:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Indiquez un fichier WAV ou FLAC.")
    raw = project_input(path, byte_limit=8 * 1024**2)
    duration, silent = audio_info(raw, suffix)
    checkpoint()
    segments = []
    execution = {"device": "none", "reused": False}
    if not silent:
        def scoped_checkpoint():
            checkpoint()
            if project_scope(project) != scope:
                reject(ErrorCode.PERMISSION_DENIED, "Le dossier de projet a changé.")

        whisper_recovery.prepare(cache, scoped_checkpoint, ask, progress)
        scoped_checkpoint()
        gpu = whisper_resident.cache_path()
        fallback = None
        if gpu:
            try:
                with reserve_model(specialist.engine, RAM_MIB, vram_mib=whisper_resident.VRAM_MIB):
                    packet, execution = whisper_resident.transcribe(
                        gpu, cache/"ggml-small.bin", HASHES["ggml-small.bin"], project, raw, suffix, scoped_checkpoint)
                    segments = decode(packet, duration, server=True)
            except whisper_resident.GpuUnavailable as error:
                fallback = str(error)
            except PlanningError as error:
                fallback = error.error.details.get("reason")
                if fallback not in ("cuda_device_unavailable", "vram_budget"):
                    raise
        if execution["device"] != "cuda":
            checkpoint()
            with reserve_model(specialist.engine, RAM_MIB):
                segments = cpu_transcribe(cache, raw, suffix, duration, scoped_checkpoint)
            execution = {"device": "cpu", "reused": False, "fallback_reason": fallback or "cuda_not_configured"}
        scoped_checkpoint()
    uncertain = any(s["uncertain"] for s in segments)
    status = ("silence" if silent else "no_transcript") if not segments else ("needs_review" if uncertain else "transcribed")
    return {"engine": specialist.engine, "execution": execution, "language": "fr", "status": status, "duration_ms": duration,
            "text": " ".join(s["text"] for s in segments), "segments": segments}


def cpu_transcribe(cache, raw, suffix, duration, checkpoint):
    with TemporaryDirectory(prefix="akasha-whisper-") as folder:
        stage = Path(folder)
        for filename, expected in HASHES.items():
            checkpoint()
            source = cache/filename if filename.endswith(".bin") else cache/"whisper"/"Release"/filename
            shutil.copyfile(source, stage/filename)
            if file_hash(stage/filename) != expected:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Empreinte Whisper inattendue.", artifact=filename)
        for filename in (*VC_RUNTIME, "vcomp140.dll"):
            shutil.copyfile(system32()/filename, stage/filename)
        for filename in (*PROBES, "whisper_guest.ps1"):
            shutil.copyfile(BENCH/"harness"/filename, stage/filename)
        (stage/("audio"+suffix)).write_bytes(raw)

        def export(compute, mount):
            args = ("exec", compute, r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", mount+r"\whisper_guest.ps1")
            return tool_stdout("hcsdiag.exe", args, 2*1024**2, 180, checkpoint)

        _, packet = run_headless_guest(stage, checkpoint, RAM_MIB, export)
        return decode(packet, duration)


def display(result):
    if not result["segments"]:
        return "Silence. Aucun texte." if result["status"] == "silence" else "Aucune parole transcrite avec certitude."
    return "\n".join(f"[{s['start_ms']/1000:.2f}–{s['end_ms']/1000:.2f} s] "
                     + ("À vérifier : " if s["uncertain"] else "") + s["text"] for s in result["segments"])
