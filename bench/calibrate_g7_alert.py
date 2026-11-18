"""Calibrate on FLEURS dev, lock the rule, then evaluate once on noisy FLEURS test."""

import argparse
import hashlib
from itertools import product
import json
import os
import subprocess
import tarfile
import wave
from pathlib import Path

import numpy as np

from akasha_brain.whisper_pilot import HASHES, decode
from bench.freeze_g7_french import REV, pcm
from bench.run_g7_asr import errors, words
from bench.run_g7_pilot import error_locations

BENCH = Path(__file__).resolve().parent
ESC = "33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6"
NOISE = {
    "1-17150-A-12.wav": ("fire", "3d278bc2034dfb83881491a8eec97de6f1239f0a5b8a7c02be46b5aab0a51609"),
    "1-17367-A-10.wav": ("rain", "d732acd2e0c7c40405968010f49f250740c86998fc416eff2ed5330fc8c89dea"),
    "1-28135-A-11.wav": ("waves", "4d04b84d490c4d9ab28a52c4c96d1b14c2f8b132fc4be38166197ae814920742"),
}
LEGACY = (.50, .80, 0)
RESULTS = BENCH/"results"
MANIFEST = BENCH/"corpora"/"g7-alert-v3.json"
LOCK = RESULTS/"g7-alert-calibration-v3.json"
CHALLENGER = RESULTS/"g7-alert-challenger-v3.json"
GRID = tuple(product((.30, .40, .50, .60, .70), (.70, .75, .80, .85, .90, .95), (0, 100, 250, 500, 1000)))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", "utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(cache, noise_dir, scratch):
    seen = set()
    for prior in ("g7-fr-v1", "g7-fr-pilot-v2"):
        seen.update(c.get("sentence_id") for c in json.loads((MANIFEST.parent/prior/"manifest.json").read_bytes())["clips"])
    noises = {}
    for name, (_, expected) in NOISE.items():
        path = noise_dir/name
        assert digest(path) == expected
        with wave.open(str(path)) as stream:
            assert stream.getnchannels() == 1 and stream.getsampwidth() == 2
            rate = stream.getframerate()
            signal = np.frombuffer(stream.readframes(stream.getnframes()), "<i2").astype(float)
        noises[name] = np.interp(np.arange(0, len(signal)-1, rate/16000), np.arange(len(signal)), signal)

    clips = []
    for split, size in (("dev", 60), ("test", 45)):
        rows = [s.split("\t") for s in (cache/f"{split}.tsv").read_text("utf-8").splitlines()]
        selected = {}
        for row in sorted(rows, key=lambda r: hashlib.sha256(("akasha-g7-v3/"+r[1]).encode()).digest()):
            if row[0] in seen or not 4 <= len(words(row[2])) <= 28 or int(row[5]) > 16000*12:
                continue
            seen.add(row[0])
            selected[row[1]] = row
            if len(selected) == size:
                break
        assert len(selected) == size
        with tarfile.open(cache/f"{split}.tar.gz", "r|gz") as archive:
            files = {Path(m.name).name: archive.extractfile(m).read() for m in archive
                     if m.isfile() and Path(m.name).name in selected}
        for i, (name, row) in enumerate(selected.items()):
            signal = pcm(files[name])
            noise = snr = None
            if split == "test":
                noise = list(NOISE)[i%3]
                snr = (8, 15, 22)[(i//3)%3]
                base = noises[noise]
                offset = int(Path(name).stem) % len(base)
                ambient = base[(np.arange(len(signal))+offset) % len(base)]
                signal += ambient*np.linalg.norm(signal)/(np.linalg.norm(ambient)*10**(snr/20))
            signal /= max(1., abs(signal).max()/0.999)
            path = scratch/name
            with wave.open(str(path), "wb") as out:
                out.setparams((1, 2, 16000, 0, "NONE", ""))
                out.writeframes(np.rint(signal*32768).astype("<i2").tobytes())
            clips.append(dict(split=split, file=name, sentence_id=row[0], reference=row[2], frames=len(signal),
                              background=noise, snr_db=snr, sha256=digest(path)))
    save(MANIFEST, dict(fleurs_revision=REV, esc50_revision=ESC, backgrounds=NOISE, clips=clips))


def collect(cache, scratch, split):
    for name, expected in HASHES.items():
        path = cache/name if name.endswith(".bin") else cache/"whisper/Release"/name
        assert digest(path) == expected, name
    rows = []
    for clip in json.loads(MANIFEST.read_bytes())["clips"]:
        if clip["split"] != split:
            continue
        wav = scratch/clip["file"]
        assert digest(wav) == clip["sha256"]
        prefix = scratch/wav.stem
        subprocess.run([cache/"whisper/Release/whisper-cli.exe", "-m", cache/"ggml-small.bin", "-f", wav,
                        "-l", "fr", "-ng", "-t", "4", "-bs", "1", "-bo", "1", "-nf", "-ojf", "-of", prefix],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=180, env={**os.environ, "OMP_NUM_THREADS": "4"})
        packet = prefix.with_suffix(".json").read_bytes()
        duration = round(clip["frames"]/16)
        segments = decode(packet, duration)
        items = [s for s in json.loads(packet.decode("utf-8", errors="replace"))["transcription"] if any(c.isalnum() for c in s["text"])
                 and s["text"].strip() != "[BLANK_AUDIO]"]
        counts = error_locations(clip["reference"], segments)
        if not segments:
            # The interface explicitly abstains. Count the entire omitted utterance as flagged.
            rows.append(dict(file=wav.name, text="", errors=len(words(clip["reference"])), fixed=True,
                             minimum=None, mean=None, clipped_ms=0, start_ms=0, end_ms=duration))
        for seg, item, n in zip(segments, items, counts, strict=True):
            scores = [t["p"] for t in item["tokens"] if 0 <= t["id"] < 50257 and any(c.isalnum() for c in t["text"])]
            rows.append(dict(file=wav.name, text=seg["text"], errors=n, start_ms=seg["start_ms"], end_ms=seg["end_ms"],
                             minimum=min(scores) if scores else None, mean=sum(scores)/len(scores) if scores else None,
                             clipped_ms=max(0,item["offsets"]["to"]-duration),
                             fixed=not scores or "invalid_text_encoding" in seg["reasons"]))
        assert sum(r["errors"] for r in rows if r["file"] == wav.name) == errors(
            words(clip["reference"]), words(" ".join(s["text"] for s in segments)))
    return rows


def flagged(row, rule):
    low, mean, clip = rule
    return row["fixed"] or row["minimum"] < low or row["mean"] < mean or row["clipped_ms"] > clip


def metrics(rows, rule):
    flags = [flagged(r, rule) for r in rows]
    return dict(exact=sum(not r["errors"] for r in rows), erroneous=sum(bool(r["errors"]) for r in rows),
                false_alerts=sum(f and not r["errors"] for f,r in zip(flags, rows)),
                missed=sum(not f and bool(r["errors"]) for f,r in zip(flags, rows)))


def calibrate(rows):
    baseline = metrics(rows, LEGACY)
    # Minimize false alerts without increasing the total missed errors on development.
    # Ties favor fewer misses, then the smallest change from the old clipping/confidence rules.
    candidates = []
    for rule in GRID:
        low, mean, clip = rule
        m = metrics(rows, rule)
        if m["missed"] <= baseline["missed"]:
            candidates.append((m["false_alerts"], m["missed"], clip, abs(mean-.8), abs(low-.5), rule))
    return min(candidates)[-1]


def lock_challenger():
    development = json.loads(LOCK.read_bytes())
    rows = development["segments"]
    candidates = []
    for rule in GRID:
        low, mean, clip = rule
        m = metrics(rows, rule)
        if m["false_alerts"] < development["baseline"]["false_alerts"]:
            # Equal weight per class. The integer numerator avoids rounding at ties.
            cost = m["false_alerts"]*m["erroneous"] + m["missed"]*m["exact"]
            candidates.append((cost, m["missed"], clip, abs(mean-.8), abs(low-.5), rule))
    rule = min(candidates)[-1]
    save(CHALLENGER, dict(calibration_sha256=digest(LOCK), rule=rule, calibration=metrics(rows, rule)))


def compare_challenger():
    trial = json.loads((RESULTS/"g7-alert-independent-v3.json").read_bytes())
    choice = json.loads(CHALLENGER.read_bytes())
    assert trial["calibration_sha256"] == choice["calibration_sha256"] == digest(LOCK)
    rows, rule = trial["segments"], choice["rule"]
    before, after = metrics(rows, LEGACY), metrics(rows, rule)
    changes = [dict(file=r["file"], start_ms=r["start_ms"], errors=r["errors"], before=r["before"],
                    after=flagged(r, rule)) for r in rows if r["before"] != flagged(r, rule)]
    save(RESULTS/"g7-alert-comparison-v3.json", dict(challenger_sha256=digest(CHALLENGER),
         independent_sha256=digest(RESULTS/"g7-alert-independent-v3.json"), rule=rule, before=before,
         after=after, changes=changes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "calibrate", "lock-challenger", "test", "compare"))
    for arg in ("cache", "noise_dir", "scratch"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    if args.stage == "lock-challenger":
        return lock_challenger()
    if args.stage == "compare":
        return compare_challenger()
    args.scratch.mkdir(exist_ok=True, parents=True)
    if args.stage == "prepare":
        prepare(args.cache, args.noise_dir, args.scratch)
        return
    if args.stage == "calibrate":
        rows = collect(args.cache, args.scratch, "dev")
        rule = calibrate(rows)
        dest = LOCK
    else:
        lock = json.loads(LOCK.read_bytes())
        assert lock["manifest"] == digest(MANIFEST)
        rule = lock["rule"]
        rows = collect(args.cache, args.scratch, "test")
        dest = RESULTS/"g7-alert-independent-v3.json"
    result = dict(manifest=digest(MANIFEST), rule=rule, baseline=metrics(rows, LEGACY), candidate=metrics(rows, rule))
    if args.stage == "test":
        result["calibration_sha256"] = digest(LOCK)
        result["accepted"] = (result["candidate"]["false_alerts"] < result["baseline"]["false_alerts"]
                              and result["candidate"]["missed"] <= result["baseline"]["missed"])
    for r in rows:
        r.update(before=flagged(r, LEGACY), after=flagged(r, rule))
    save(dest, {**result, "segments":rows})
    print(result)


if __name__ == "__main__":
    main()
