"""Synthèse dans le bac Windows et contrôle des mots sensibles par une transcription CPU indépendante."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import unicodedata

from akasha_brain.piper_voice import synthesize
from akasha_brain.whisper_pilot import cache_path, HASHES
from bench.run_guided_repair import BENCH, file_hash

CORPUS = BENCH/"corpora/g8-siwis-fr-v1"


def normalize(text):
    text = unicodedata.normalize("NFC", text).casefold()
    text = text.replace("€", " euros ")
    text = re.sub(r"\b(\d{1,2})\s*h\b", r"\1 heures", text)
    return re.sub(r"[^\w]+", " ", text).strip()


def transcribe(wav):
    cache = cache_path()
    engine = cache/"whisper/Release/whisper-cli.exe"
    model = cache/"ggml-small.bin"
    for name, checksum in HASHES.items():
        assert file_hash(model if name == model.name else engine.parent/name) == checksum
    with TemporaryDirectory() as tmp:
        pcm = Path(tmp)/"check.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", wav, "-ar", "16000", pcm], check=True)
        subprocess.run([engine, "-m", model, "-f", pcm, "-ng", "-t", "4", "-l", "fr", "-bs", "1", "-bo", "1",
                        "-nf", "-otxt", "-of", Path(tmp)/"asr"], capture_output=True, check=True)
        return (Path(tmp)/"asr.txt").read_text("utf-8").strip()


def run(holdout=False):
    rows = []
    protocol = json.loads((CORPUS/"reserve.json").read_bytes())
    phrases = protocol["phrases"] if holdout else json.loads((CORPUS/"phrases.json").read_bytes())
    for item in phrases:
        data, proof = synthesize(item["text"], lambda: None)
        wav = CORPUS/(item["id"]+".wav")
        wav.write_bytes(data)
        transcript = transcribe(wav)
        checks = [any(normalize(term) in normalize(transcript) for term in variants) for variants in item["critical"]]
        rows.append({**proof, "id": item["id"], "wav_sha256": file_hash(wav), "asr": transcript, "checks": checks})
        print(item["id"], proof, transcript, checks, flush=True)
    report = {"voice_revision": "375a0fe641dea077c2a47b4e9a056d6da521eed3", "engine": "Piper 2023.11.14-2 CPU",
              "check": "whisper.cpp small français, CPU", "clips": rows, "all_critical_terms": all(all(r["checks"]) for r in rows)}
    name = "g8-siwis-fr-reserve-v1.json" if holdout else "g8-siwis-fr-v1.json"
    if holdout:
        gate = protocol["promotion"]
        desktop = json.loads((BENCH/"results/g8-desktop-v1.json").read_bytes())
        report["protocol_sha256"] = file_hash(CORPUS/"reserve.json")
        report["passed"] = (report["all_critical_terms"] and all(r["sandbox_stopped"]
            and r["seconds_until_wav"] <= gate["max_seconds_until_wav"]
            and 0 < r["guest_peak_bytes"] <= gate["max_guest_peak_mib"]*1024**2 for r in rows)
            and desktop["seconds_to_stopped"] <= gate["max_seconds_to_stop"] and desktop["windows_output_released"])
    (BENCH/"results"/name).write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", "utf-8")
    return report.get("passed", report["all_critical_terms"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", action="store_true")
    raise SystemExit(0 if run(parser.parse_args().holdout) else 1)
