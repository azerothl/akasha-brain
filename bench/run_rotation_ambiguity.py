"""Compare le sélecteur PNG figé à une sonde d'ambiguïté sur des motifs carrés."""

import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from bench import run_learned_rotation_transfer as learned


REPORT = learned.previous.RESULTS / "rotation-ambiguity-v1.json"
# Chaque motif reçoit le même fond et des bords entièrement vides.
PATTERNS = {
    "arrow": ((3, 1), (2, 2), (3, 2), (4, 2), (3, 3), (3, 4), (3, 5)),
    "off_axis": ((2, 4),),
    "half_turn": ((1, 2), (5, 4)),
    "quarter_turn": ((3, 1), (5, 3), (3, 5), (1, 3)),
}


def probe(source, goal_corners, model, reference=None):
    before = learned.corners(source)
    plans = [name for name, steps in learned.PLANS.items()
             if learned.predict(before, steps, model) == goal_corners]
    initial_count = len(plans)
    examined = 0
    if len(plans) > 1 and reference is not None:
        # Chaque groupe de quatre positions suit la même permutation que les coins.
        side = source.width
        seen = set()
        for y in range(1, side-1):
            for x in range(1, side-1):
                if (x, y) in seen or len(plans) <= 1:
                    continue
                orbit = ((x, y), (side-1-y, x), (side-1-x, side-1-y), (y, side-1-x))
                seen.update(orbit)
                before = tuple(source.getpixel(p) for p in orbit)
                goal = tuple(reference.getpixel(p) for p in orbit)
                examined += 1
                plans = [p for p in plans if learned.predict(before, learned.PLANS[p], model) == goal]
    return {"corner_matches": initial_count, "interior_groups_examined": examined, "remaining": plans,
            "status": "selected" if len(plans) == 1 else "abstain",
            "plan": plans[0] if len(plans) == 1 else None}


def run():
    frozen = json.loads(learned.MODEL.read_bytes())
    if frozen != json.loads(json.dumps(learned.train())):
        raise RuntimeError("Le modèle ou le protocole antérieur a changé.")
    cases = []
    for name, points in PATTERNS.items():
        image = Image.new("L", (7, 7))
        for point in points:
            image.putpixel(point, 197)
        # Injecter uniquement l'image dans le banc historique, conserver toute sa décision.
        with patch.object(learned, "fixture", return_value=image):
            historical = learned.evaluate({**frozen, "holdout": [(0, *image.size)]})
        orientations = list(learned.views(image))
        for case in historical["cases"]:
            initial, target = case["initial"], case["target"]
            source, expected = orientations[initial], orientations[target]
            unique = sum(view.tobytes() == expected.tobytes() for view in orientations) == 1
            given = learned.corners(expected)
            limited = probe(source, given, frozen["model"])
            visual = probe(source, given, frozen["model"], expected)
            verified = None
            if visual["plan"] is not None:
                png = learned.apply_plan(source, learned.PLANS[visual["plan"]])
                with Image.open(BytesIO(png)) as actual:
                    verified = (actual.format == "PNG" and actual.mode == expected.mode
                                and actual.size == expected.size and actual.tobytes() == expected.tobytes())
            if limited["status"] != "abstain" or (unique and verified is not True) or (not unique and visual["plan"] is not None):
                raise AssertionError((name, initial, target, limited, visual, verified))
            cases.append({"pattern": name, "initial": initial, "target": target,
                          "orientation_identifiable": unique, "frozen": case["trials"]["learned"],
                          "corners_only": limited, "with_reference": visual, "verified_png": verified})
    return {"model_sha256": learned.previous.source_hash(learned.MODEL),
            "protocol_sha256": learned.previous.source_hash(__file__),
            "summary": {"cases": len(cases), "frozen_choices": dict(Counter(c["frozen"]["plan"] for c in cases)),
                        "frozen_exact_png": sum(c["frozen"]["passed"] for c in cases),
                        "probe_corners_only": dict(Counter(c["corners_only"]["status"] for c in cases)),
                        "probe_with_reference": dict(Counter(c["with_reference"]["status"] for c in cases)),
                        "probe_exact_png": sum(c["verified_png"] is True for c in cases)},
            "cases": cases}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=REPORT)
    report_path = cli.parse_args().output
    result = run()
    serialized = json.dumps(result, indent=2) + "\n"
    if report_path.exists():
        if report_path.read_text(encoding="utf-8") != serialized:
            raise ValueError("Le rejeu diffère du rapport existant.")
    else:
        with report_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    print(result["summary"])
