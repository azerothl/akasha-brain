"""Rejoue les quatre motifs par le registre et le planificateur de conversation."""

import argparse
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from akasha_brain.conversation_planning import execute_intents, infer_intent, load_conversation_catalog, references
from contracts.akasha_contracts.errors import AkashaError
from bench.run_learned_rotation_transfer import views
from bench.run_rotation_ambiguity import PATTERNS


def ask(project, request, catalog):
    refs = references(request)
    steps = infer_intent(None, "", request, refs, catalog, selected=True)
    reply, = execute_intents(request, steps, refs, project, catalog)
    return reply


def verify(project):
    catalog = load_conversation_catalog()
    cases = []
    for motif, points in PATTERNS.items():
        image = Image.new("L", (7, 7))
        for point in points:
            image.putpixel(point, 197)
        poses = list(views(image))
        for start, source in enumerate(poses):
            source.save(project / "source.png")
            for target, expected in enumerate(poses):
                expected.save(project / "repère.png")
                originals = {f.name: f.read_bytes() for f in project.iterdir()}
                matches = [i * 90 for i, view in enumerate(views(source)) if view.tobytes() == expected.tobytes()]
                for mode, suffix in (("visual", ""), ("corners", " selon les coins uniquement")):
                    reply = ask(project, "Oriente source.png comme repère.png" + suffix, catalog)
                    abstention = mode == "corners" or len(matches) != 1
                    if isinstance(reply, AkashaError):
                        assert abstention and reply.details["outcome"] == "abstain", reply
                        proof = reply.details
                    else:
                        assert not abstention and reply.routing["specialist"] == "png-orientation"
                        proof = reply.output.proof
                        with Image.open(BytesIO(reply.output.png)) as actual:
                            assert actual.format == "PNG" and actual.size == expected.size
                            assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
                    assert proof["corner_candidates"] == [0, 90, 180, 270]
                    assert proof["evidence"] == ("corners" if mode == "corners" else "visual_pattern")
                    assert proof["matching_rotations"] == (proof["corner_candidates"] if mode == "corners" else matches)
                    assert originals == {f.name: f.read_bytes() for f in project.iterdir()}
                    cases.append({"motif": motif, "initial": start, "target": target, "mode": mode,
                                  "outcome": "abstain" if abstention else "verified_png",
                                  "angles": proof["matching_rotations"]})
    return {"cases": cases, "summary": {mode: {status: sum(c["mode"] == mode and c["outcome"] == status for c in cases)
                                               for status in ("abstain", "verified_png")}
                                        for mode in ("corners", "visual")}}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    with TemporaryDirectory() as temp:
        result = verify(Path(temp))
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    print(result["summary"])
