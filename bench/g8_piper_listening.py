"""Rend le témoin et la variante de prosodie dans le même parcours G8 hors ligne."""

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from akasha_brain import piper_voice


BENCH = Path(__file__).resolve().parent
CORPUS = BENCH / "corpora/g8-prosodie-v1/phrases.json"
RAW = BENCH.parent / ".venv/g8-listening/raw"
SETTINGS = {"current": "--length_scale 1.1", "adjusted": "--length_scale 1.0 --sentence_silence 0.32"}


def measure(variant, number, text, repetition, directory=RAW):
    with TemporaryDirectory() as tmp:
        bench = Path(tmp)
        harness = bench / "harness"
        harness.mkdir()
        for probe in piper_voice.PROBES:
            shutil.copyfile(BENCH / "harness" / probe, harness / probe)
        script = (BENCH / "harness/piper_guest.ps1").read_text("utf-8")
        if script.count(SETTINGS["current"]) != 1:
            raise ValueError("Le réglage du pilote de référence a changé.")
        (harness / "piper_guest.ps1").write_text(script.replace(SETTINGS["current"], SETTINGS[variant]), "utf-8")
        with patch.object(piper_voice, "BENCH", bench):
            started = perf_counter()
            wav, proof = piper_voice.synthesize(text, lambda: None)
            ready = perf_counter() - started
    folder = directory / variant
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{number}{'-repeat' if repetition else ''}.wav"
    (folder / filename).write_bytes(wav)
    metric = dict(phrase=number, filename=filename, repeat=repetition, ready_seconds=ready, **proof)
    print(variant, filename, round(ready, 3), flush=True)
    return metric


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--controle", action="store_true",
                        help="Rejouer la phrase 2 après la préparation des dépendances, dans un dossier séparé.")
    args = parser.parse_args()
    phrases = json.loads(CORPUS.read_bytes())
    rows = {variant: [] for variant in SETTINGS}
    directory = RAW / "controle" if args.controle else RAW
    sequence = (2,) if args.controle else (1, 2, 3, 1)
    # Alterner la position du témoin pour répartir les effets d’ordre sur la machine.
    for index, number in enumerate(sequence):
        for variant in (list(SETTINGS) if index % 2 == 0 else list(reversed(SETTINGS))):
            rows[variant].append(measure(variant, number, phrases[number - 1], index == 3, directory))
            (directory / variant / "report.json").write_text(json.dumps({
                "settings": SETTINGS[variant], "device": "CPU, Windows Sandbox neuf par demande",
                "streaming": False, "rows": rows[variant]
            }, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
