"""Prépare une écoute locale anonyme et garde la clé séparée de la planche."""

from array import array
import argparse
from base64 import b64encode
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
from random import SystemRandom
import re
import subprocess
import wave


BENCH = Path(__file__).resolve().parent
CORPUS = BENCH / "corpora/g8-prosodie-v1"
RAW = BENCH.parent / ".venv/g8-listening/raw"
RESULTS = BENCH / "results"
ARMS = ("current", "adjusted", "qwen")
LETTERS = "ABC"


def volume(path):
    measure = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                              "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                             capture_output=True, check=True, encoding="utf-8", errors="replace")
    data = json.loads(re.search(r'\{\s*"input_i".*?\}', measure.stderr, re.S)[0])
    return float(data["input_i"]), float(data["input_tp"])


def sound_onset(path):
    """Début de la première fenêtre de 10 ms au-dessus de −50 dBFS RMS sur le signal natif."""
    with wave.open(str(path), "rb") as stream:
        assert stream.getnchannels() == 1 and stream.getsampwidth() == 2
        frames = array("h", stream.readframes(stream.getnframes()))
        rate = stream.getframerate()
    width = round(rate * .01)
    threshold = 32768**2 * 10**(-50 / 10)
    for offset in range(0, len(frames) - width + 1, width):
        if sum(x*x for x in frames[offset:offset+width]) > threshold * width:
            return offset / rate
    raise ValueError(f"Silence sur tout le fichier {path}")


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "utf-8")


def timings(run_id):
    reports = {}
    for variant in ("current", "adjusted"):
        captures = []
        for directory in (RAW / variant, RAW / "controle" / variant):
            info = json.loads((directory / "report.json").read_bytes())
            for row in info["rows"]:
                onset = sound_onset(directory / row["filename"])
                captures.append({**row, "onset_s": onset, "first_sound_s": row["ready_seconds"] + onset,
                                 "separate_control": directory.parent.name == "controle"})
        reports[variant] = {"setup": info["settings"], "device": info["device"], "runs": captures}
    reports["qwen"] = json.loads((RAW / "qwen/report.json").read_bytes())
    write_json(RESULTS / f"g8-prosodie-{run_id}-latences.json", {
        "lot": run_id, "corpus_sha256": sha256((CORPUS / "phrases.json").read_bytes()).hexdigest(),
        "definition": "Horloge monotone jusqu’au retour du signal jouable, plus le silence initial du PCM natif. "
                      "Fenêtres de 10 ms, seuil −50 dBFS RMS. Sortie physique non chronométrée.",
        "protocol": "Trois phrases puis répétition de la première. Cache disque du système non purgé. "
                    "Un bac CPU neuf à chaque appel Piper. Qwen résident CUDA après le premier appel. "
                    "Les deux premières séries Piper chevauchent la préparation de dépendances sur disque. "
                    "Contrôle supplémentaire sur la phrase 2 après les essais Qwen.",
        "profiles": reports
    })


def prepare(stream=False):
    phrases = json.loads((CORPUS / "phrases.json").read_bytes())
    raw = RAW.parent / "stream-v1" if stream else RAW
    variants = ("reference", "nuance", "sobre") if stream else ARMS
    corpus = BENCH / "corpora/g8-streaming-v1" if stream else CORPUS
    prefix = "g8-streaming" if stream else "g8-prosodie"
    files = {(n, arm): raw / arm / f"{n}.wav" for n in range(1, len(phrases)+1) for arm in variants}
    inputs = {f"{n}-{arm}": sha256(path.read_bytes()).hexdigest() for (n, arm), path in files.items()}
    run_id = sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:12]
    keypath = RESULTS / f"{prefix}-{run_id}-cle.json"
    if keypath.exists():
        order = json.loads(keypath.read_bytes())["ordre"]
    else:
        rand = SystemRandom()
        # Carré latin randomisé : chaque moteur occupe chaque position une fois.
        arms = rand.sample(variants, 3)
        shifts = rand.sample(range(3), 3)
        order = [arms[i:] + arms[:i] for i in shifts]
        write_json(keypath, {"lot": run_id, "ordre": order, "sources_sha256": inputs})
    public = corpus / f"ecoute-{run_id}"
    public.mkdir(parents=True, exist_ok=True)
    levels = {key: volume(path) for key, path in files.items()}
    # Gain constant sur tout le fichier. Garder au moins 1,5 dB de marge sur chaque crête.
    target = min(-23, *(loudness-peak-1.5 for loudness, peak in levels.values()))
    html = []
    check = []
    for n, (phrase, arms) in enumerate(zip(phrases, order, strict=True), start=1):
        html.append(f"<section><h2>Phrase {n}</h2><p lang='fr'>« {escape(phrase)} »</p><div class='clips'>")
        for letter, arm in zip(LETTERS, arms, strict=True):
            source = files[n, arm]
            dest = public / f"{n}-{letter}.wav"
            gain = target - levels[n, arm][0]
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source),
                            "-map_metadata", "-1", "-af", f"volume={gain:.3f}dB", "-ac", "1", "-ar", "24000",
                            "-bitexact", "-c:a", "pcm_s16le", str(dest)], check=True)
            actual, peak = volume(dest)
            assert math.isfinite(actual) and abs(actual-target) < .35 and peak < -.5
            check.append({"id": f"{n}-{letter}", "sha256": sha256(dest.read_bytes()).hexdigest(),
                          "LUFS": actual, "dBTP": peak, "onset_s": sound_onset(dest if stream else source)})
            encoded = b64encode(dest.read_bytes()).decode("ascii")
            html.append(f"<label>Version {letter}<audio aria-label='Phrase {n}, version {letter}' "
                        f"controls preload='none' src='data:audio/wav;base64,{encoded}'></audio></label>")
        options = "".join(f"<option>{v}</option>" for v in (*LETTERS, "Ex æquo", "Aucune"))
        html.append(f"</div><label>Ma préférence <select required id='p{n}'><option value=''>Choisir</option>"
                    f"{options}</select></label> <label>Remarque <input id='r{n}' maxlength='500' "
                    "placeholder='Facultatif'></label></section>")
    page = (BENCH / "g8_listening_template.html").read_text("utf-8")
    instruction = ("Pour les deux premières phrases, écoute si la question sonne juste. "
                   "Pour les trois, juge la sobriété de la lecture. Les mots en relief et les pauses "
                   "te semblent-ils naturels ?" if stream else
                   "Prête attention à la montée des questions, aux mots mis en relief et aux pauses.")
    page = page.replace("{{consigne}}", instruction)
    (public / "ecoute.html").write_text(page.replace("{{clips}}", "\n".join(html)).replace("{{lot}}", run_id), "utf-8")
    write_json(RESULTS / f"{prefix}-{run_id}-verification.json", {"lot": run_id, "cible_LUFS": target, "clips": check})
    if not stream:
        timings(run_id)
    print(public)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream-v1", action="store_true", help="Préparer le lot des trois lectures Qwen.")
    prepare(stream=parser.parse_args().stream_v1)
