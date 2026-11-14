"""Mesure OCR du banc (spec §12.2) : image synthétique au contenu connu.

Génère un PNG via PIL (aucun affichage requis), l'OCRise avec RapidOCR
(CPU), compare au texte attendu et mesure le temps mur. Le premier usage
télécharge les poids ONNX (accord requis, spec §13.7).
Usage : .\\.venv\\Scripts\\python.exe bench/harness/measure_ocr.py [--out dir]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import unicodedata

LINES = [
    "Café — été",
    "Préparer la réunion",
    "Envoyer la facture",
    "première ligne",
    "deuxième ligne",
]


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().lower()


def fold(text: str) -> str:
    """Plie les accents (le modèle de reconnaissance les omet) pour comparer."""
    decomposed = unicodedata.normalize("NFKD", norm(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def build_image(path: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 40)
    img = Image.new("RGB", (900, 60 * len(LINES) + 40), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in LINES:
        draw.text((20, y), line, fill="black", font=font)
        y += 60
    img.save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(tempfile_dir(), "akasha-ocr"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    img_path = os.path.join(args.out, "synthetic.png")

    from rapidocr_onnxruntime import RapidOCR

    build_image(img_path)
    engine = RapidOCR()
    t0 = time.perf_counter()
    result, _elapse = engine(img_path)
    wall = time.perf_counter() - t0

    found_words = set(fold(" ".join(box[1] for box in (result or []))).split())
    missing = [line for line in LINES
               if not set(fold(line).split()).issubset(found_words)]
    print(f"moteur=rapidocr-onnxruntime mur_s={wall:.1f} lignes={len(result or [])}")
    print(f"mots_reconnus={sorted(found_words)}")
    if missing:
        print(f"MANQUANT={missing}")
        return 1
    print("OCR PASS : tous les mots retrouvés (comparaison sans accents).")
    print("Limite : le modèle omet les accents — l'OCR n'est jamais l'oracle,"
          " le contrôle d'état indépendant décide (spec §12.3).")
    return 0


def tempfile_dir() -> str:
    import tempfile

    return tempfile.gettempdir()


if __name__ == "__main__":
    raise SystemExit(main())
