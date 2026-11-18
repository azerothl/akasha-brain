"""Banc G7 Windows. Une CLI native par fichier, quatre threads, processus séquentiels."""

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
from statistics import median
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter
import unicodedata
import winreg

from bench.freeze_g7_french import ROOT


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def words(line):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", line).casefold())


def errors(reference, hypothesis):
    row = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        nxt = [i]
        for j, other in enumerate(hypothesis, 1):
            nxt.append(min(row[j]+1, nxt[-1]+1, row[j-1]+(word != other)))
        row = nxt
    return row[-1]


def summarize(result):
    clips = {c["wav"]: c for c in json.loads((ROOT/"manifest.json").read_bytes())["clips"]}
    summary = {}
    for engine in ("vibe", "whisper"):
        rows = [r for r in result["runs"] if r["engine"] == engine and r["split"] == "test"]
        first = [r for r in rows if r["repeat"] == 1]
        second = {r["wav"]: r for r in rows if r["repeat"] == 2}
        if len(first) != len(second) or len(first) != sum(c["split"] == "test" for c in clips.values()):
            raise ValueError("Comparaison incomplète.")
        n = sum(r["reference_words"] for r in first)
        duration = sum(r["audio_s"] for r in first)
        wall = sum(r["wall_s"] for r in rows)/2
        conditions = {}
        for condition in ("clean", "noise_10dB"):
            group = [r for r in first if clips[r["wav"]]["condition"] == condition]
            conditions[condition] = [sum(r["word_errors"] for r in group), sum(r["reference_words"] for r in group)]
        bounded = 0
        for r in first:
            end = 0
            ok = bool(r["offsets_ms"])
            for s in r["offsets_ms"]:
                ok &= end <= s["from"] < s["to"] <= round(1000*r["audio_s"])
                end = s["to"]
            bounded += ok
        summary[engine] = {
            "errors": sum(r["word_errors"] for r in first), "words": n, "conditions": conditions,
            "wer_pct": round(100*sum(r["word_errors"] for r in first)/n, 2), "audio_s": duration,
            "mean_total_s": round(wall, 3), "rtf": round(wall/duration, 4),
            "process_s_per_audio_min": round(60*wall/duration, 2),
            "peak_ws_mib": round(max(r["peak_ws_bytes"] for r in rows)/2**20, 2),
            "median_model_load_ms": round(median(r["model_load_ms"] for r in rows), 1),
            "hypotheses_reproduced": sum(r["hypothesis"] == second[r["wav"]]["hypothesis"] for r in first),
            "bounded_timestamps": bounded,
            "names_detected": sum(sum(r["names_found"].values()) for r in first),
            "expected_names": sum(len(r["names_found"]) for r in first),
            "silence": [r["hypothesis"] for r in result["runs"] if r["engine"] == engine and r["split"] == "control"]}
    return summary


class Memory(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (key, ctypes.c_size_t) for key in ("peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                                           "nonpaged", "pagefile", "peak_pagefile")]


def measure(cmd, env, work):
    info = Memory()
    info.cb = ctypes.sizeof(info)
    api = ctypes.windll.psapi.GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    peak = 0
    with (work/"stdout").open("wb") as stdout, (work/"stderr").open("wb") as stderr:
        start = perf_counter()
        with subprocess.Popen(cmd, cwd=work, env=env, stdout=stdout, stderr=stderr) as proc:
            while True:
                if api(int(proc._handle), ctypes.byref(info), info.cb):
                    peak = max(peak, info.peak_ws)
                try:
                    proc.wait(timeout=.02)
                    break
                except subprocess.TimeoutExpired:
                    if perf_counter() - start > 180:
                        proc.kill()
                        raise TimeoutError(cmd[0])
            elapsed = perf_counter() - start
            if api(int(proc._handle), ctypes.byref(info), info.cb):
                peak = max(peak, info.peak_ws)
    log = (work/"stderr").read_text("utf-8", errors="replace")
    if proc.returncode or not peak:
        raise RuntimeError(f"{cmd[0]}: {proc.returncode}, peak={peak}\n{log[-1200:]}")
    return elapsed, peak, (work/"stdout").read_text("utf-8"), log


def run(cache, report):
    clips = json.loads((ROOT/"manifest.json").read_bytes())["clips"]
    for clip in clips:
        if digest(ROOT/clip["wav"]) != clip["sha256"]:
            raise ValueError(clip["wav"])
    whisper = cache/"whisper/Release/whisper-cli.exe"
    vibe = cache/"build/bin/asr_infer.exe"
    lm = cache/"vibeasr-lm-i2_s-embed-q6_k.gguf"
    vae = cache/"vibeasr-vae-encoder-i8_s.gguf"
    small = cache/"ggml-small.bin"
    env = {**os.environ, "OMP_NUM_THREADS": "4",
           "PATH": str(cache/"llvm-mingw-20261117-ucrt-x86_64/bin")+os.pathsep+os.environ["PATH"]}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
        cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    result = {"cpu": cpu, "windows": platform.version(), "threads": 4,
              "manifest_sha256_lf": hashlib.sha256((ROOT/"manifest.json").read_text("utf-8").encode()).hexdigest(),
              "hashes": {p.name: digest(p) for p in (whisper, vibe, lm, vae, small, *sorted(whisper.parent.glob("*.dll")))},
              "runs": []}
    for repeat in range(2):
        for index, clip in enumerate(clips):
            output = ROOT/clip["wav"]
            order = ("vibe", "whisper") if (index + repeat) % 2 == 0 else ("whisper", "vibe")
            for engine in order:
                with TemporaryDirectory() as folder:
                    work = Path(folder)
                    if engine == "whisper":
                        cmd = [whisper, "-m", small, "-f", output, "-l", "fr", "-ng", "-t", "4",
                               "-bs", "1", "-bo", "1", "-nf", "-oj", "-of", "transcript"]
                    else:
                        cmd = [vibe, "--lm-model", lm, "--vae-model", vae, "--audio", output,
                               "-t", "4", "--greedy", "--prompt-format", "text", "--max-tokens", "256"]
                    wall, peak, stdout, log = measure(cmd, env, work)
                    if engine == "whisper":
                        segments = json.loads((work/"transcript.json").read_bytes())["transcription"]
                        transcript = " ".join(s["text"].strip() for s in segments)
                        times = [s["offsets"] for s in segments]
                        load = float(re.search(r"load time\s*=\s*([\d.]+) ms", log)[1])
                    else:
                        transcript = stdout.strip()
                        times = []
                        load = sum(float(re.search(which+r" model loading:\s*([\d.]+) ms", log)[1])
                                   for which in ("VAE", "LM"))
                    ref, hyp = words(clip["reference"]), words(transcript)
                    names = {name: (" "+" ".join(words(name))+" ") in (" "+" ".join(hyp)+" ") for name in clip["names"]}
                    row = {"engine": engine, "repeat": repeat+1, "wav": clip["wav"], "split": clip["split"],
                           "audio_s": clip["frames"]/16000, "wall_s": round(wall, 4), "model_load_ms": load,
                           "peak_ws_bytes": peak, "reference_words": len(ref), "word_errors": errors(ref, hyp),
                           "hypothesis": transcript, "offsets_ms": times, "names_found": names}
                    result["runs"].append(row)
                    print(engine, clip["wav"], round(wall, 2), row["word_errors"], flush=True)
    result["summary"] = summarize(result)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", "utf-8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("cache", type=Path)
    cli.add_argument("report", type=Path)
    args = cli.parse_args()
    run(args.cache.resolve(), args.report)
