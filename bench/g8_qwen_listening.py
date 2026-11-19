"""Local G8 listening trial. Run with .venv/g8-listening/env/Scripts/python.exe."""

import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import wave
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".venv/g8-listening"
OUTPUT = PRIVATE / "raw/qwen"
CORPUS = ROOT / "bench/corpora/g8-prosodie-v1/phrases.json"
REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
MODEL = PRIVATE / "models" / REVISION
SPEAKER = "Vivian"
STYLE = (
    "Parle en français sur un ton conversationnel naturel. Fais entendre les questions, "
    "marque clairement les corrections et garde un débit posé pour la narration."
)
SEED = 7319


def verify_model():
    meta = json.loads((MODEL / "hub-metadata.json").read_text(encoding="utf-8"))
    if (meta["id"], meta["sha"]) != (REPO, REVISION):
        raise ValueError("Unexpected model or revision")
    verified = {}
    for item in meta["siblings"]:
        name = item["rfilename"]
        if name in {"README.md", ".gitattributes"}:
            continue
        path = MODEL / name
        size = path.stat().st_size
        if size != item["size"]:
            raise ValueError(f"Unexpected size for {name}: {size}")
        with path.open("rb") as src:
            sha = hashlib.file_digest(src, "sha256").hexdigest()
        if item.get("lfs"):
            matches = sha == item["lfs"]["sha256"]
        else:
            git_blob = f"blob {size}\0".encode() + path.read_bytes()
            matches = hashlib.sha1(git_blob).hexdigest() == item["blobId"]
        if not matches:
            raise ValueError(f"Unexpected digest for {name}")
        verified[name] = {"bytes": size, "sha256": sha}
    return verified


def encode_audio(samples, rate):
    import numpy as np

    samples = np.asarray(samples)
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ValueError("Expected finite mono audio")
    pcm = np.rint(samples.astype(np.float64) * 32768).clip(-32768, 32767).astype("<i2")
    width = round(rate * 0.010)
    windows = pcm[:pcm.size // width * width].reshape(-1, width).astype(np.float64) / 32768
    starts = np.flatnonzero(np.mean(windows ** 2, axis=1) >= 10 ** (-50 / 10))
    if not starts.size:
        raise ValueError("No complete 10 ms window reached -50 dBFS RMS")
    with io.BytesIO() as container:
        with wave.open(container, "wb") as wav:
            wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            wav.writeframes(pcm.tobytes())
        data = container.getvalue()
    return data, {
        "sample_rate_hz": rate, "frames": pcm.size, "duration_ms": pcm.size * 1000 / rate,
        "onset_ms": int(starts[0]) * width * 1000 / rate, "wav_bytes": len(data),
        "wav_sha256": hashlib.sha256(data).hexdigest(),
    }


def main():
    phrases = json.loads(CORPUS.read_text(encoding="utf-8-sig"))
    if not isinstance(phrases, list) or len(phrases) != 3 or not all(
        isinstance(text, str) and text.strip() for text in phrases
    ):
        raise ValueError("Expected exactly three nonempty French phrases")
    if any((OUTPUT / name).exists() for name in ("1.wav", "2.wav", "3.wav", "report.json")):
        raise FileExistsError("A listening trial already has outputs here")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      GRADIO_ANALYTICS_ENABLED="False", HF_HOME=str(PRIVATE / "hf"))

    # Start with dependencies and CUDA uninitialized in this process.
    cold_start = perf_counter_ns()
    import torch
    from qwen_tts import Qwen3TTSModel
    from transformers import set_seed

    model = Qwen3TTSModel.from_pretrained(
        str(MODEL), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    torch.cuda.synchronize()
    loaded = perf_counter_ns()
    param = next(model.model.parameters())
    if param.device.type != "cuda" or param.dtype != torch.bfloat16:
        raise RuntimeError(f"Unexpected model placement: {param.device} {param.dtype}")
    runs = []
    artifacts = {}
    for take, phrase_id in enumerate((1, 2, 3, 1)):
        start = perf_counter_ns() if take else cold_start
        set_seed(SEED)
        with torch.inference_mode():
            audios, rate = model.generate_custom_voice(
                text=phrases[phrase_id - 1], language="French", speaker=SPEAKER, instruct=STYLE,
                non_streaming_mode=True,
            )
        returned = perf_counter_ns()
        elapsed = (returned - start) / 1e6
        data, stats = encode_audio(audios[0], rate)
        filename = f"{phrase_id}.wav" if take < 3 else None
        if filename:
            artifacts[filename] = data
        runs.append({"phrase_id": phrase_id, "phase": "cold" if not take else "warm",
                     "repeat": take == 3, "file": filename, "complete_audio_ms": elapsed,
                     "request_start_ns": start, "complete_audio_return_ns": returned,
                     "first_non_silent_ms": elapsed + stats["onset_ms"], **stats})
        print(f"take {take + 1}: phrase {phrase_id}, complete PCM {elapsed:.1f} ms", flush=True)

    report = {
        "model": {"id": REPO, "revision": REVISION, "files": verify_model()},
        "environment": {
            "windows": platform.platform(), "gpu": torch.cuda.get_device_name(0),
            "driver_version": subprocess.check_output([
                "nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader", "-i", "0"
            ], text=True).strip(),
            "device": str(param.device), "dtype": str(param.dtype), "attention": "sdpa",
            "python": platform.python_version(), "cuda_runtime": torch.version.cuda,
            "packages": {p: version(p) for p in (
                "qwen-tts", "torch", "torchaudio", "transformers", "accelerate",
                "huggingface-hub", "numpy", "safetensors",
            )},
        },
        "speaker": SPEAKER, "instruction": STYLE, "language": "French", "seed_per_request": SEED,
        "streaming": False, "phrases": phrases, "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        "cold_load_with_imports_ms": (loaded - cold_start) / 1e6,
        "timing": (
            "perf_counter_ns to complete host waveform. Cold includes Python library imports, "
            "CUDA initialization and model load. OS file cache uncontrolled. Warm uses the same "
            "resident model. WAV encoding and I/O excluded. first_non_silent_ms adds the start "
            "of the first non-overlapping 10 ms PCM16 window with RMS >= -50 dBFS to the return "
            "time, assuming immediate playback."
        ),
        "runs": runs,
    }
    for name, data in artifacts.items():
        (OUTPUT / name).write_bytes(data)
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] == ["--verify-model"]:
        print(json.dumps(verify_model(), indent=2))
    elif sys.argv[1:]:
        raise SystemExit("Use --verify-model or no arguments for the listening trial")
    else:
        main()
