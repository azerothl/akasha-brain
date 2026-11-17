"""Rejoue la planification G3, la recomposition et la reprise RapidOCR."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from PIL import Image, ImageDraw, ImageFont

from akasha_brain.capability_recovery import Recovery
from akasha_brain.conversation_planning import (
    execute_intents, explicit_media_step, load_conversation_catalog, plan_intent, references,
)

MISSING = {"tool": "missing", "refs": [], "detail": "capacité locale absente"}
INSPECT = {"tool": "project.inspect", "refs": [], "detail": ""}


def ask(state, request, proposal, project, catalog):
    reply, = execute_intents(request, proposal, references(request), project, catalog, recovery=state)
    return reply


def measure(action, *, samples=21):
    values = []
    for trial in range(samples):
        started = perf_counter()
        action()
        if trial:
            values.append((perf_counter() - started) * 1000)
    return round(median(values), 3)


def verify(runtime, root):
    project = root / "project"
    project.mkdir()
    (project / "package.json").write_text('{"name":"fixture-g3","scripts":{"test":"node --test"}}', encoding="utf-8")
    (project / "sample.test.js").write_text("require('node:test')('synthetic', () => {});\n", encoding="utf-8")
    (project / "avant.md").write_text("Ancien\n", encoding="utf-8")
    (project / "apres.md").write_text("Nouveau\n", encoding="utf-8")
    catalog = load_conversation_catalog()
    database = root / "recovery.sqlite"
    state = Recovery(database, runtime, lambda message: print(message, flush=True), lambda: False)
    check = ask(state, "Vérifie le projet choisi", INSPECT, project, catalog)
    assert check.plan.capability == "project.inspect"
    assert "node --test" in check.output.summary()
    candidate = ask(state, "Compare « avant.md » et « apres.md ».", MISSING, project, catalog)
    assert candidate.diagnostic["passed"] and candidate.output.endswith("-Ancien\n+Nouveau\n")
    utf16 = "Ancien\n".encode("utf-16")
    (project / "unicode.txt").write_bytes(utf16)
    converted = ask(state, "Compare « unicode.txt » et « apres.md ».", MISSING, project, catalog)
    assert converted.diagnostic["level"] == "B" and converted.diagnostic["passed"]
    assert converted.output.endswith("-Ancien\n+Nouveau\n")
    assert (project / "unicode.txt").read_bytes() == utf16
    request = "Lis « avant.md » puis compare « avant.md » et « apres.md »."
    read, compare = execute_intents(request, [MISSING, MISSING], references(request), project, catalog, recovery=state)
    assert read.output["lines"][0]["text"] == "Ancien" and compare.output.endswith("-Ancien\n+Nouveau\n")
    assert read.diagnostic == compare.diagnostic and read.diagnostic["level"] == "C"

    def missing():
        reply = ask(state, "Convertis guide.md en PDF", MISSING, project, catalog)
        assert reply.details["outcome"] == "missing"

    plan_ms = measure(lambda: plan_intent("Vérifie le projet choisi", INSPECT, [], project, catalog))
    missing_ms = measure(missing)

    capture = Image.new("RGB", (620, 180), "white")
    ImageDraw.Draw(capture).text((30, 50), "ALPHA 35", fill="black", font=ImageFont.load_default(size=58))
    capture.save(project / "capture.png")
    request = "Lis le texte de « capture.png »"
    proposal = explicit_media_step(request, references(request))
    ocr_times = []
    for _ in range(2):
        started = perf_counter()
        ocr = ask(state, request, proposal, project, catalog)
        assert hasattr(ocr, "plan"), getattr(ocr, "message", ocr)
        assert ocr.plan.capability == "image.ocr" and "ALPHA35" in ocr.output.upper().replace(" ", "")
        ocr_times.append(round(perf_counter() - started, 3))
    with closing(sqlite3.connect(database)) as db:
        checked = json.loads(db.execute("SELECT report FROM gap_reports WHERE capability = 'image.ocr'").fetchone()[0])
        assert checked["events"] == ["reused", "resumed"]
        (capability, proof), = db.execute("SELECT capability, proof FROM local_capabilities").fetchall()
        adaptation = json.loads(proof)["adaptation"]
        assert capability == "image.ocr" and adaptation == {"level": "D", "capability": capability, "passed": True}
    assert (project / "avant.md").read_text(encoding="utf-8") == "Ancien\n"
    assert (project / "apres.md").read_text(encoding="utf-8") == "Nouveau\n"
    return {"status": "passed" if missing_ms < 2000 else "failed", "covered_project": True,
            "local_recomposition": candidate.diagnostic, "encoding_conversion": converted.diagnostic,
            "candidate_skill": read.diagnostic, "ocr_adaptation": adaptation,
            "uncovered_pdf": "missing",
            "ocr_qualified_wall_s": ocr_times[0], "ocr_reused_wall_s": ocr_times[1], "ocr_reused": True,
            "timing": {"inspect_plan_ms": plan_ms, "missing_end_to_end_ms": missing_ms, "samples": 20,
                       "missing_threshold_ms": 2000, "model_loaded": False}}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--runtime", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    with TemporaryDirectory(prefix="akasha-g3-resolution-") as directory:
        result = verify(args.runtime.resolve(strict=True), Path(directory).resolve())
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
