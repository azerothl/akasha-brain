"""Fige des extraits FLEURS fr_fr à partir des archives et TSV officiels."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import tarfile
import wave

import numpy as np


ROOT = Path(__file__).parent / "corpora" / "g7-fr-v1"
REV = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
# Fichier source, bruit blanc ajouté à 10 dB, expressions nommées à suivre.
SELECTION = {
    "dev": [("14203199903136889342", False, ["Auckland"])],
    "test": [("17999210160761730950", False, ["Aerosmith"]),
             ("3661632639400662062", False, ["Afrique du Sud", "SANParks"]),
             ("8969527857548188961", False, ["Voie lactée", "Sagittaire"]),
             ("7989253100718399733", True, []), ("118005971910520590", False, []),
             ("12217957387078475556", False, ["Sagittaire"]),
             ("15942080413960253441", True, []), ("9747669897173511466", False, [])]}


def pcm(raw):
    offset = 12
    while offset + 8 <= len(raw):
        chunk, size = struct.unpack_from("<4sI", raw, offset)
        start = offset + 8
        if chunk == b"fmt ":
            assert struct.unpack_from("<HHIIHH", raw, start) == (3, 1, 16000, 64000, 4, 32)
        if chunk == b"data":
            return np.frombuffer(raw[start:start+size], dtype="<f4").astype("float64")
        offset = start + size + size % 2
    raise ValueError("WAV FLEURS invalide")


def save(name, samples):
    path = ROOT / (name + ".wav")
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", ""))
        out.writeframes(np.clip(np.rint(samples * 32768), -32768, 32767).astype("<i2").tobytes())
    return {"wav": path.name, "frames": len(samples), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def freeze(cache):
    ROOT.mkdir(parents=True, exist_ok=True)
    clips = []
    for split, selection in SELECTION.items():
        rows = {r[1]: r for r in (line.split("\t") for line in (cache / f"{split}.tsv").read_text("utf-8").splitlines())}
        wanted = {key + ".wav" for key, _, _ in selection}
        with tarfile.open(cache / f"{split}.tar.gz", "r|gz") as archive:
            files = {item.name.split("/")[-1]: archive.extractfile(item).read() for item in archive
                     if item.isfile() and item.name.split("/")[-1] in wanted}
        for key, noisy, names in selection:
            name = key + ".wav"
            samples = pcm(files[name])
            if noisy:
                noise = np.random.default_rng(int(key)).standard_normal(len(samples))
                samples += noise * np.linalg.norm(samples) / (np.linalg.norm(noise) * 10**0.5)
            row = rows[name]
            assert len(samples) == int(row[5])
            clips.append({**save(key, samples), "split": split, "sentence_id": row[0], "voice_group": row[6],
                          "condition": "noise_10dB" if noisy else "clean", "reference": row[2], "names": names})
    clips.append({**save("silence", np.zeros(48000)), "split": "control", "condition": "silence",
                  "reference": "", "names": []})
    data = {"source": f"https://huggingface.co/datasets/google/fleurs/tree/{REV}/data/fr_fr",
            "attribution": "FLEURS, Conneau et al., Google, CC BY 4.0; conversions PCM16, deux ajouts de bruit.",
            "license": "https://creativecommons.org/licenses/by/4.0/", "clips": clips}
    (ROOT / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    freeze(parser.parse_args().cache)
