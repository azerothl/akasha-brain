"""Mesure par bloc PCM. Chaque invocation démarre un processus CUDA neuf."""

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from time import perf_counter

from bench.g8_qwen_listening import CORPUS, MODEL, PRIVATE, REVISION, SEED, SPEAKER, STYLE, encode_audio


OUT = PRIVATE / "stream-v1"
STYLES = {
    "reference": STYLE,
    "nuance": "Réponds comme dans une conversation en français de France. Entre immédiatement dans la phrase. "
              "Fais monter la voix sur la dernière syllabe des vraies questions, notamment « prévenir ». "
              "Une correction tient dans un seul mouvement. Garde les affirmations simples, calmes et sobres.",
    "sobre": "Français parlé de France, voix tranquille, directe et complice. Démarre sans hésiter. "
             "Pour une question, attends réellement une réponse : termine sur une montée nette et brève. "
             "Pour une information, garde une mélodie discrète et descendante, sans emphase ni effet de scène.",
}


def capture(engine, mode, text, style, start):
    import numpy as np
    from transformers import set_seed

    set_seed(SEED)
    params = dict(text=text, language="French", speaker=SPEAKER, instruct=STYLES[style],
                  non_streaming_mode=True, max_new_tokens=256)
    if mode == "stream":
        packets = engine.generate_custom_voice_streaming(**params, chunk_size=4)
    else:
        waves, rate = engine.generate_custom_voice(**params)
        packets = [(waves[0], rate, None)]

    blocks, chunks = [], []
    end_of_buffer = None
    first_sound = None
    gaps = []
    for signal, rate, _ in packets:
        block = np.asarray(signal, dtype=np.float32).reshape(-1).copy()
        ready = perf_counter() - start
        if not block.size:
            continue
        assert rate == 24000 and np.isfinite(block).all()
        play_from = ready if end_of_buffer is None else max(ready, end_of_buffer)
        if end_of_buffer is not None and ready > end_of_buffer:
            gaps.append(ready-end_of_buffer)
        if first_sound is None:
            width = rate // 100
            windows = block[:block.size // width * width].reshape(-1, width)
            hits = np.flatnonzero(np.mean(windows**2, axis=1) >= 1.e-5)
            if hits.size:
                first_sound = play_from + int(hits[0]) * width / rate
        end_of_buffer = play_from + len(block) / rate
        blocks.append(block)
        chunks.append(dict(ready_s=ready, frames=len(block)))
    done = perf_counter() - start
    assert first_sound is not None
    if mode == "stream":
        assert len(chunks) > 1 and first_sound < chunks[-1]["ready_s"]
    wav, stats = encode_audio(np.concatenate(blocks), rate)
    return wav, dict(first_sound_s=first_sound, complete_s=done, blocks=chunks,
                     playback_gap_s=gaps, **stats)


def run(mode, session):
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", GRADIO_ANALYTICS_ENABLED="False",
                      CUDA_CACHE_PATH=str(PRIVATE / "cuda-cache"), HF_HOME=str(PRIVATE / "hf"),
                      NUMBA_CACHE_DIR=str(PRIVATE / "numba"))
    phrases = json.loads(CORPUS.read_bytes())
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{mode}-{session}.json"
    if path.exists():
        raise FileExistsError(path)
    cold = perf_counter()
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    engine = FasterQwen3TTS.from_pretrained(str(MODEL), device="cuda:0", dtype=torch.bfloat16,
                                            attn_implementation="sdpa", max_seq_len=768)
    torch.cuda.synchronize()
    loaded_s = perf_counter() - cold
    parameter = next(engine.model.model.parameters())
    assert parameter.is_cuda and "4080 SUPER" in torch.cuda.get_device_name()
    runs = []
    plan = [("reference", 1), ("reference", 1), ("reference", 2), ("reference", 3)]
    if mode == "stream" and session == 1:
        plan += [(style, n) for n in (1, 2, 3) for style in ("nuance", "sobre")]
    for i, (style, n) in enumerate(plan):
        with torch.inference_mode():
            wav, result = capture(engine, mode, phrases[n-1], style, cold if i == 0 else perf_counter())
        runs.append(dict(style=style, phrase=n, cold=i == 0, **result))
        if mode == "stream" and session == 1 and i != 1:
            directory = OUT / style
            directory.mkdir(exist_ok=True)
            (directory / f"{n}.wav").write_bytes(wav)
        print(mode, session, style, n, f"{result['first_sound_s']:.3f}s", len(result["blocks"]), flush=True)
    report = dict(mode=mode, process=os.getpid(), repetition=session, weights_revision=REVISION,
                  corpus_sha256=hashlib.sha256(CORPUS.read_bytes()).hexdigest(), load_s=loaded_s,
                  gpu=torch.cuda.get_device_name(), dtype=str(parameter.dtype), packages={
                      name:version(name) for name in ("faster-qwen3-tts","qwen-tts","transformers","torch")
                  }, speaker=SPEAKER, styles=STYLES, seed=SEED, chunk_codec_frames=4, runs=runs)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("stream","full"))
    parser.add_argument("session", type=int)
    args = parser.parse_args()
    run(args.mode, args.session)
