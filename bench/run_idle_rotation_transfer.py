"""Gel sur Notes puis comparaison appariée de deux règles de sélection sur des PNG."""

import argparse
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, __version__ as pillow_version

from akasha_brain import desktop_state, idle_simulation
from bench import run_phase5_notes_action_selection as notes


RESULTS = Path(__file__).parent / "results"
FREEZE = RESULTS / "idle-rotation-freeze-v1.json"
REPORT = RESULTS / "idle-rotation-transfer-v1.json"
ARMS = ("reference", "candidate")
# Catalogue ordonné par longueur, avec priorité stable au premier plan en cas d'égalité.
PLANS = {"copy": (), "right": (1,), "left": (-1,), "turn_around": (1, 1)}
# Images attendues dessinées indépendamment des opérations Pillow et du prédicteur.
VIEWS = (
    ((1, 2, 3), (4, 5, 6)),
    ((4, 1), (5, 2), (6, 3)),
    ((6, 5, 4), (3, 2, 1)),
    ((3, 6), (2, 5), (1, 4)),
)


def choose(allowed, matches, arm):
    if arm == "candidate":
        return next((name for name in allowed if matches[name]), allowed[0])
    return allowed[0]


def source_hash(name):
    return sha256(Path(name).read_text(encoding="utf-8").encode()).hexdigest()


def freeze():
    scores = dict.fromkeys(ARMS, 0)
    for case in idle_simulation.synthetic_cases(23, 8):
        trials = idle_simulation.replay_case(case)["trials"]
        before = idle_simulation.snapshot(case["pid"], case["saved"])
        goal = {"exact_fixture_present": True, "pid_relation": "different" if case["restart"] else "any"}
        for arm in ARMS:
            selection = notes.select_plan(idle_simulation.PLANS, goal, before, use_predictor=arm == "candidate")
            matches = {name: outcome["matches_goal"] for name, outcome in selection["projections"].items()}
            if choose(selection["admissible"], matches, arm) != trials[arm]["chosen"]:
                raise RuntimeError("La règle portable diverge du sélecteur Notes.")
            scores[arm] += trials[arm]["passed"]
    return {"protocol": "rotation-transfer-v1", "source_seed": 23, "source_cases": 8,
            "scores": scores, "selected": "candidate" if scores["candidate"] > scores["reference"] else "reference",
            "sha256_utf8_lf": {Path(f).name: source_hash(f) for f in
                                (__file__, idle_simulation.__file__, notes.__file__, desktop_state.__file__)},
            "pillow": pillow_version, "pairs": list(product(range(4), repeat=2)),
            "criterion": "more verified PNGs than reference and zero paired regressions"}


def pixels(view):
    return bytes(value for row in view for value in row)


def execute(folder, initial, target, arm):
    view = VIEWS[initial]
    source = folder / "source.png"
    destination = folder / "result.png"
    Image.frombytes("L", (len(view[0]), len(view)), pixels(view)).save(source)
    allowed = [name for name, steps in PLANS.items() if steps or initial == target]
    matches = {name: (initial + sum(PLANS[name])) % 4 == target for name in allowed}
    plan = choose(allowed, matches, arm)
    with Image.open(source) as original:
        output = original.copy()
    for step in PLANS[plan]:
        rotation = Image.Transpose.ROTATE_270 if step == 1 else Image.Transpose.ROTATE_90
        output = output.transpose(rotation)
    output.save(destination)
    expected = VIEWS[target]
    with Image.open(destination) as image:
        passed = (image.format == "PNG" and image.mode == "L" and
                  image.size == (len(expected[0]), len(expected)) and image.tobytes() == pixels(expected))
    return {"plan": plan, "passed": passed, "source_sha256": sha256(source.read_bytes()).hexdigest(),
            "output_sha256": sha256(destination.read_bytes()).hexdigest()}


def evaluate(frozen):
    cases = []
    selected = frozen["selected"]
    for index, (initial, target) in enumerate(frozen["pairs"]):
        arms = {}
        for arm in (ARMS if index % 2 == 0 else reversed(ARMS)):
            with TemporaryDirectory() as folder:
                arms[arm] = execute(Path(folder), initial, target, arm)
        if arms["reference"]["source_sha256"] != arms["candidate"]["source_sha256"]:
            raise RuntimeError("Les entrées PNG de la paire diffèrent.")
        cases.append({"initial": initial, "target": target, "arms": arms})
    scores = {arm: sum(c["arms"][arm]["passed"] for c in cases) for arm in ARMS}
    losses = sum(c["arms"]["reference"]["passed"] and not c["arms"][selected]["passed"] for c in cases)
    return {"freeze_sha256_utf8_lf": source_hash(FREEZE), "selected": selected, "scores": scores,
            "paired_regressions": losses, "criterion_met": scores[selected] > scores["reference"] and not losses,
            "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "evaluate"))
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    current = json.dumps(freeze(), indent=2) + "\n"
    if args.stage == "freeze":
        if FREEZE.exists():
            if FREEZE.read_text(encoding="utf-8") != current:
                raise ValueError("Gel existant différent. Versionner un nouveau protocole.")
        else:
            with FREEZE.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(current)
        print(current)
    else:
        if FREEZE.read_text(encoding="utf-8") != current:
            raise ValueError("Le protocole, les intrants ou la sélection ont changé depuis le gel.")
        report = evaluate(json.loads(current))
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        print(report["scores"], report["criterion_met"])


if __name__ == "__main__":
    main()
