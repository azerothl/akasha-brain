"""Paired cold/warm French ASR benchmark on a single Windows NVIDIA GPU."""

import argparse
import ctypes as ct
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time


class Adapter(ct.Structure):
    _fields_ = [("luid", ct.c_char * 8), ("handle", ct.c_uint32)]


class MemoryQuery(ct.Structure):
    _fields_ = [("process", ct.c_void_p), ("adapter", ct.c_uint32), ("segment", ct.c_uint32),
                ("budget", ct.c_uint64), ("usage", ct.c_uint64), ("reserved", ct.c_uint64),
                ("available", ct.c_uint64), ("index", ct.c_uint32)]


def open_gpu():
    cuda = ct.WinDLL("nvcuda")
    adapter = Adapter()
    node = ct.c_uint()
    if cuda.cuInit(0) or cuda.cuDeviceGetLuid(ct.byref(adapter), ct.byref(node), 0):
        raise RuntimeError("LUID du GPU CUDA inaccessible")
    if ct.windll.gdi32.D3DKMTOpenAdapterFromLuid(ct.byref(adapter)):
        raise RuntimeError("Adaptateur Windows inaccessible")
    return adapter.handle


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", "utf-8")


def vibe_worker(model_dir, audio_file, folder):
    (folder/"worker.pid").write_text(str(os.getpid()), "ascii")
    import torch
    from vibevoice_asr_streaming_inference_from_file import (
        VibeVoiceASRForConditionalGeneration, VibeVoiceASRProcessor, load_audio_use_ffmpeg, load_frame_config)

    config = load_frame_config(str(model_dir))
    processor = VibeVoiceASRProcessor.from_pretrained(str(model_dir))
    assert processor.tokenizer.text_chunk_end_id is not None
    model = VibeVoiceASRForConditionalGeneration.from_pretrained(
        str(model_dir), dtype=torch.bfloat16, attn_implementation="sdpa").to("cuda:0").eval()
    assert all(p.is_cuda for p in model.parameters())
    for phase in ("cold", "warm"):
        audio, rate = load_audio_use_ffmpeg(str(audio_file), resample=True, target_sr=config["sample_rate"])
        chunks = [text for _, _, text in model.streaming_generate(
            audio_tensor=torch.from_numpy(audio), tokenizer=processor.tokenizer, sample_rate=rate,
            chunk_duration=config["chunk_duration"], text_audio_delay=config["text_audio_delay"],
            max_new_tokens_per_chunk=256, temperature=0.0, context_info=None)]
        torch.cuda.synchronize()
        save(folder/(phase+".json"), dict(raw="".join(chunks), gpu=torch.cuda.get_device_name(0),
                                         allocated=torch.cuda.max_memory_allocated()))


def measure(command, env, folder, adapter):
    peak = 0
    with (folder/"engine.log").open("wb") as log:
        start = time.time_ns()
        with subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT) as process:
            query = MemoryQuery(process=int(process._handle), adapter=adapter)
            worker_handle = None
            pidfile = folder/"worker.pid"
            deadline = time.monotonic()+300
            while process.poll() is None:
                if worker_handle is None and pidfile.exists():
                    pid = pidfile.read_text("ascii").strip()
                    if pid:
                        open_process = ct.windll.kernel32.OpenProcess
                        open_process.restype = ct.c_void_p
                        worker_handle = open_process(0x0400, False, int(pid))
                        if not worker_handle:
                            raise ct.WinError()
                        query.process = worker_handle
                status = ct.windll.gdi32.D3DKMTQueryVideoMemoryInfo(ct.byref(query))
                if not status:
                    peak = max(peak, query.usage)
                if time.monotonic() > deadline:
                    process.kill()
                    raise TimeoutError(command[0])
                time.sleep(.01)
            if worker_handle:
                ct.windll.kernel32.CloseHandle(ct.c_void_p(worker_handle))
    log_text = (folder/"engine.log").read_text("utf-8", errors="replace")
    if process.returncode or not peak:
        raise RuntimeError(f"exit={process.returncode} VRAM={peak}\n{log_text[-2200:]}")
    cold, warm = [(folder/(phase+".json")).stat().st_mtime_ns for phase in ("cold", "warm")]
    if not start < cold < warm:
        raise ValueError("Horodatages de sortie invalides")
    return (cold-start)/1e9, (warm-cold)/1e9, peak, log_text


def spoken(raw):
    text = re.sub(r"\bSpeaker\s*\d+\s*:", " ", raw, flags=re.IGNORECASE)
    return re.sub(r"\[(?:noise|environmental sounds|silence|blank_audio|music|laughter)\]",
                  " ", text, flags=re.IGNORECASE).strip()


def run(args):
    from bench.run_g7_asr import ROOT, digest, errors, words
    manifest = ROOT/"manifest.json"
    clips = json.loads(manifest.read_bytes())["clips"]
    cpu = json.loads((ROOT.parent.parent/"results/g7-asr-fr-cpu-v1.json").read_bytes())
    for clip in clips:
        assert digest(ROOT/clip["wav"]) == clip["sha256"]
    small = args.cpu/"ggml-small.bin"
    assert digest(small) == cpu["hashes"][small.name]
    shard_hashes = (
        "788e6206a158c614e1e6777ab843baf64ca8a3f555e3cb72c26d5d79b925d4b9",
        "4d58b3ce47ac6b0ac5d3b142d54e56f10e02a928cf016b493e9e6a3f91beb75d",
        "884b560dcd3024436d8827d32c7e211c545751c099df4ee75101c1ee2196f427",
    )
    for index, expected in enumerate(shard_hashes, 1):
        assert digest(args.cache/"model"/f"model-{index:05d}-of-00003.safetensors") == expected
    exe = args.cache/"whisper/Release/whisper-cli.exe"
    vendor = args.cache/"VibeVoice"
    revision = subprocess.check_output(["git", "-c", f"safe.directory={vendor.as_posix()}", "-C", str(vendor),
                                        "rev-parse", "HEAD"], text=True).strip()
    env = dict(os.environ, HF_HUB_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
               CUDA_VISIBLE_DEVICES="0", OMP_NUM_THREADS="4",
               PYTHONPATH=os.pathsep.join(str(p) for p in (args.cache/"extra", vendor, vendor/"demo")))
    adapter = open_gpu()
    report = dict(gpu=subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                  "--format=csv,noheader"], text=True).strip(), corpus_sha256=digest(manifest),
                  whisper_version="1.8.3 CUDA 12.4", whisper_model_sha256=digest(small), whisper_cli_sha256=digest(exe),
                  vibe_revision="4262d23d8a539a6530cf64fbd0b1751ef9a30853", vibe_source_revision=revision,
                  cold="process creation to first completed transcript; filesystem cache uncontrolled",
                  warm="second transcription of same file in same process; new request",
                  vram="sampled WDDM per-process local segment CurrentUsage on CUDA adapter, 10 ms sleep",
                  runs=[])
    for i, clip in enumerate(clips):
        wav = ROOT/clip["wav"]
        for engine in (("whisper", "vibe") if i%2 == 0 else ("vibe", "whisper")):
            with TemporaryDirectory() as tmp:
                folder = Path(tmp)
                if engine == "whisper":
                    cmd = [exe, "-m", small, "-f", wav, "-f", wav, "-l", "fr", "-t", "4", "-bs", "1", "-bo", "1",
                           "-nf", "-oj", "-of", folder/"cold", "-of", folder/"warm"]
                else:
                    cmd = [args.vibe_python, Path(__file__).resolve(), "--worker", args.cache/"model", wav, folder]
                cold, warm, peak, log = measure(cmd, env, folder, adapter)
                outputs = {}
                for phase in ("cold", "warm"):
                    packet = json.loads((folder/(phase+".json")).read_bytes())
                    if engine == "whisper":
                        assert "using CUDA0 backend" in log
                        raw = " ".join(s["text"].strip() for s in packet["transcription"])
                    else:
                        assert "4080 SUPER" in packet["gpu"] and packet["allocated"] > 0
                        raw = packet["raw"]
                    hypothesis = spoken(raw)
                    outputs[phase] = dict(raw=raw, hypothesis=hypothesis,
                                          errors=errors(words(clip["reference"]), words(hypothesis)))
                row = dict(engine=engine, wav=wav.name, split=clip["split"], condition=clip["condition"],
                           reference_words=len(words(clip["reference"])), audio_s=clip["frames"]/16000,
                           cold_s=cold, warm_s=warm, peak_vram_bytes=peak, **outputs)
                report["runs"].append(row)
                save(args.report, report)
                print(engine, wav.name, round(cold,2), round(warm,2), peak//2**20, flush=True)
    summarize(report)
    save(args.report, report)


def summarize(report):
    """Recalculate spoken WER from raw output and the original frozen references."""
    from bench.run_g7_asr import ROOT, digest, errors, words
    manifest = ROOT/"manifest.json"
    assert digest(manifest) == report["corpus_sha256"]
    clips = {c["wav"]: c for c in json.loads(manifest.read_bytes())["clips"]}
    assert sorted((r["engine"], r["wav"]) for r in report["runs"]) == sorted(
        (engine, name) for engine in ("whisper", "vibe") for name in clips)
    for row in report["runs"]:
        ref = words(clips[row["wav"]]["reference"])
        for phase in ("cold", "warm"):
            output = row[phase]
            output["hypothesis"] = spoken(output["raw"])
            output["errors"] = errors(ref, words(output["hypothesis"]))
    report["summary"] = {}
    for engine in ("whisper", "vibe"):
        rows = [r for r in report["runs"] if r["split"]=="test" and r["engine"]==engine]
        summary = dict(words=sum(r["reference_words"] for r in rows), audio_s=sum(r["audio_s"] for r in rows),
                       peak_vram_mib=max(r["peak_vram_bytes"] for r in rows)/2**20)
        for phase in ("cold", "warm"):
            count = sum(r[phase]["errors"] for r in rows)
            summary[phase] = dict(errors=count, wer_pct=100*count/summary["words"],
                                  seconds=sum(r[phase+"_s"] for r in rows))
            conditions = {}
            for condition in ("clean", "noise_10dB"):
                group = [r for r in rows if r["condition"] == condition]
                conditions[condition] = dict(errors=sum(r[phase]["errors"] for r in group),
                                             words=sum(r["reference_words"] for r in group))
            summary[phase]["conditions"] = conditions
        report["summary"][engine] = summary


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        vibe_worker(*map(Path, sys.argv[2:]))
    elif sys.argv[1:2] == ["--summarize"]:
        path = Path(sys.argv[2])
        result = json.loads(path.read_bytes())
        summarize(result)
        save(path, result)
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        for name in ("cache", "cpu", "vibe_python", "report"):
            parser.add_argument(name, type=Path)
        run(parser.parse_args())
