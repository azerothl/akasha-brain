"""Vérifie le chemin OCR de la conversation dans Windows Sandbox."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from akasha_brain.capability_recovery import Recovery
from akasha_brain.conversation_planning import (
    execute_intents, explicit_media_step, infer_intent, load_conversation_catalog, references,
)


def replay(root: Path, runtime: Path) -> dict:
    project = root / "project"
    project.mkdir()
    capture = Image.new("RGB", (620, 180), "white")
    ImageDraw.Draw(capture).text((30, 50), "ALPHA 35", fill="black", font=ImageFont.load_default(size=58))
    capture.save(project / "capture.png")

    database = root / "recovery.sqlite"
    recovery = Recovery(database, runtime, print, lambda: False)
    request = "Lis le texte de « capture.png »"
    refs = references(request)
    catalog = load_conversation_catalog()
    started = perf_counter()
    with patch("akasha_brain.conversation_planning.server", side_effect=AssertionError("Rbitnet appelé pour l’OCR")), \
         patch("akasha_brain.image_recovery.run", side_effect=AssertionError("Moteur image appelé pour l’OCR")):
        steps = infer_intent(None, "", request, refs, catalog, selected=True)
        assert steps == [explicit_media_step(request, refs)]
        reply, = execute_intents(request, steps, refs, project, catalog, recovery=recovery)
    elapsed = perf_counter() - started
    assert reply.plan.capability == "image.ocr" and "ALPHA35" in reply.output.upper().replace(" ", "")
    with closing(sqlite3.connect(database)) as db:
        report = json.loads(db.execute("SELECT report FROM gap_reports WHERE capability = 'image.ocr'").fetchone()[0])
        capability, proof = db.execute("SELECT capability, proof FROM local_capabilities").fetchone()
    qualification = json.loads(proof)
    routing = report["diagnostic"]["routing"]
    residency = report["diagnostic"]["residency"]
    assert capability == "image.ocr" and report["status"] == "resumed"
    assert qualification["sandbox_stopped"] and qualification["routing"] == routing
    assert routing["specialist"] == "vision-rapidocr" and routing["reason"] == "declared_modality_contract"
    assert residency["engine"] == "onnxruntime" and residency["ram_reserved_mib"] == 4096
    assert residency["inside_sandbox"] is True
    return {"status": "passed", "text_verified": True, "qualified_in_windows_sandbox": True,
            "events": report["events"], "routing": routing, "residency": residency,
            "other_model_calls_blocked_in_probe": True, "wall_s": round(elapsed, 3)}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--runtime", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    with TemporaryDirectory(prefix="akasha-specialist-ocr-") as directory:
        result = replay(Path(directory).resolve(), args.runtime.resolve(strict=True))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
