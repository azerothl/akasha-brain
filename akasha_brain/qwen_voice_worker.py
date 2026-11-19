"""Dedicated, offline Vivian process. Executed as an absolute script under python -I."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from contextlib import closing


REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
# bench/results/g8-prosodie-79ee9ff269b9-latences.json, qwen.model.files.
FILES = {
    "config.json": "17a07f527a1c25ea30b4e023a184482a23d3e279d697b1dc81b1bde498d29cf9",
    "generation_config.json": "f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa",
    "merges.txt": "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
    "model.safetensors": "38b1d5971bdbd982b561cccec982669a53b0537c3cf5e9bd4778ed07bb2f5137",
    "preprocessor_config.json": "efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119",
    "speech_tokenizer/config.json": "ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167",
    "speech_tokenizer/configuration.json": "6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd",
    "speech_tokenizer/model.safetensors": "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258",
    "speech_tokenizer/preprocessor_config.json": "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb",
    "tokenizer_config.json": "dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
}
HEADER = struct.Struct("!cII")  # kind, request id, payload bytes
MAX_FRAME = 64 * 1024
MAX_PCM = 24_000 * 2 * 30
MAX_REQUEST = 4096
MAX_TEXT = 220


class WorkerFailure(Exception):
    pass


def verify_model(home):
    model = home / "models" / REVISION
    allowed = set(FILES) | {"speech_tokenizer", "hub-metadata.json", ".gitattributes", "README.md"}
    if model.resolve(strict=True) != model:
        raise WorkerFailure("model_integrity")
    for path in model.rglob("*"):
        if path.relative_to(model).as_posix() not in allowed or path.resolve(strict=True) != path:
            raise WorkerFailure("model_integrity")
    for name, expected in FILES.items():
        with (model / name).open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise WorkerFailure("model_integrity")
    return model


def offline(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg",
                 "socket.gethostbyname", "socket.gethostbyaddr"}:
        raise PermissionError("Réseau désactivé pour la voix locale.")


def pcm16(signal, rate):
    import numpy as np

    block = np.asarray(signal)
    if rate != 24_000 or block.ndim != 1 or not np.isfinite(block).all():
        raise WorkerFailure("invalid_audio")
    return np.rint(block.astype(np.float64) * 32768).clip(-32768, 32767).astype("<i2").tobytes()


def load_synthesizer(home):
    model = verify_model(home)
    import torch
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise WorkerFailure("cuda_device_unavailable")
    from faster_qwen3_tts import FasterQwen3TTS
    from transformers import set_seed

    engine = FasterQwen3TTS.from_pretrained(str(model), device="cuda:0", dtype=torch.bfloat16,
                                             attn_implementation="sdpa", max_seq_len=768,
                                             local_files_only=True)
    parameter = next(engine.model.model.parameters())
    if not parameter.is_cuda or parameter.dtype != torch.bfloat16:
        raise WorkerFailure("cuda_device_unavailable")

    def synthesize(text, prompt):
        set_seed(7319)
        with torch.inference_mode():
            packets = engine.generate_custom_voice_streaming(
                text=text, speaker="Vivian", language="French", instruct=prompt,
                non_streaming_mode=True, chunk_size=4, max_new_tokens=256)
            for signal, rate, _ in packets:
                yield pcm16(signal, rate)

    return synthesize


def join_job(name):
    # The Windows venv launcher can be a different process from the CUDA interpreter.
    # Join before loading anything. Parent death or cancellation kills the entire job.
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    api.OpenJobObjectW.restype = wintypes.HANDLE
    api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = api.OpenJobObjectW(1, False, name)  # JOB_OBJECT_ASSIGN_PROCESS
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.AssignProcessToJobObject(handle, -1):  # GetCurrentProcess pseudo-handle
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        api.CloseHandle(handle)


def send(out, kind, request, payload=b""):
    out.write(HEADER.pack(kind, request, len(payload)))
    out.write(payload)
    out.flush()


def main():
    home = Path(sys.argv[1])
    if os.name == "nt":
        join_job(sys.argv[2])
    # Reserve stdout for frames, including during imports that print native diagnostics.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes
        ctypes.windll.kernel32.SetStdHandle(wintypes.DWORD(-11), wintypes.HANDLE(msvcrt.get_osfhandle(2)))
    sys.addaudithook(offline)
    send(out, b"R", 0, struct.pack("!I", os.getpid()))
    synthesize = None
    request = 0
    try:
        while line := sys.stdin.buffer.readline(MAX_REQUEST + 1):
            if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                raise WorkerFailure("invalid_request")
            request, text, prompt = json.loads(line)
            if (type(request) is not int or not 1 <= request <= 0xffffffff
                    or not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\0" in text
                    or not isinstance(prompt, str) or not 1 <= len(prompt) <= 512):
                raise WorkerFailure("invalid_request")
            if synthesize is None:
                synthesize = load_synthesizer(home)
            total = 0
            stopped = False
            with closing(synthesize(text, prompt)) as blocks:
                for block in blocks:
                    total += len(block)
                    if len(block) % 2 or total > MAX_PCM:
                        raise WorkerFailure("invalid_audio")
                    for start in range(0, len(block), MAX_FRAME):
                        send(out, b"P", request, block[start:start + MAX_FRAME])
                        credit = sys.stdin.buffer.readline(3)
                        if credit == b"-\n":
                            stopped = True
                            break
                        if credit != b"+\n":
                            raise WorkerFailure("invalid_credit")
                    if stopped:
                        break
            if not total:
                raise WorkerFailure("empty_audio")
            send(out, b"S" if stopped else b"D", request)
    except Exception as error:
        reason = str(error) if isinstance(error, WorkerFailure) else type(error).__name__
        send(out, b"E", request, reason.encode("ascii", "replace")[:128])
    finally:
        out.close()


if __name__ == "__main__":
    main()
