"""Apprend les transitions des coins par observation, puis teste le modèle gelé sur des PNG."""

import argparse
from io import BytesIO
from itertools import permutations
import json
from pathlib import Path
from random import Random

from PIL import Image, __version__ as pillow_version

from bench import run_idle_rotation_transfer as previous


TRAIN = ((23, 3, 5), (29, 6, 4))
HOLDOUT = ((71, 4, 7), (73, 5, 5), (79, 8, 3))
MODEL = previous.RESULTS / "learned-rotation-freeze-v1.json"
REPORT = previous.RESULTS / "learned-rotation-transfer-v1.json"
MOTORS = {"A": Image.Transpose.ROTATE_270, "B": Image.Transpose.ROTATE_90}
PLANS = {"copy": "", "A": "A", "B": "B", "AA": "AA"}


def fixture(seed, width, height):
    data = bytes(Random(seed).sample(range(256), width * height))
    return Image.frombytes("L", (width, height), data)


def corners(image):
    w, h = image.size
    return tuple(image.getpixel(p) for p in ((0, 0), (w-1, 0), (w-1, h-1), (0, h-1)))


def apply_plan(image, actions):
    for action in actions:
        image = image.transpose(MOTORS[action])
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def fit(traces):
    model = {}
    for action in ("A", "B"):
        pairs = [(row["before"], row["after"]) for row in traces if row["action"] == action]
        viable = [order for order in permutations(range(4))
                  if all(tuple(before[i] for i in order) == after for before, after in pairs)]
        if len(viable) != 1:
            raise ValueError(f"Transition ambiguë ou incompatible pour {action}.")
        model[action] = viable[0]
    return model


def train():
    policy = json.loads(previous.FREEZE.read_bytes())
    if policy["sha256_utf8_lf"][Path(previous.__file__).name] != previous.source_hash(previous.__file__):
        raise ValueError("Le sélecteur diffère de la version gelée sur Notes.")
    traces = []
    for spec in TRAIN:
        source = fixture(*spec)
        for action in MOTORS:
            with Image.open(BytesIO(apply_plan(source, action))) as observed:
                traces.append({"seed": spec[0], "action": action,
                               "before": corners(source), "after": corners(observed)})
    return {"policy": policy["selected"], "policy_freeze": previous.source_hash(previous.FREEZE),
            "protocol_sha256": previous.source_hash(__file__), "pillow": pillow_version,
            "train": TRAIN, "holdout": HOLDOUT, "traces": traces, "model": fit(traces),
            "criterion": "more verified images than reference, zero paired regressions, beats swapped model"}


def views(image):
    # Oracle indépendant du moteur Pillow. Chaque matrice contient aussi les pixels intérieurs.
    width, height = image.size
    raw = image.tobytes()
    rows = [raw[y*width:(y+1)*width] for y in range(height)]
    for _ in range(4):
        yield Image.frombytes("L", (len(rows[0]), len(rows)), b"".join(rows))
        rows = [bytes(row) for row in zip(*reversed(rows))]


def predict(state, steps, model):
    for action in steps:
        state = tuple(state[i] for i in model[action])
    return state


def evaluate(frozen):
    cases = []
    model = frozen["model"]
    swapped = {"A": model["B"], "B": model["A"]}
    for spec in frozen["holdout"]:
        images = list(views(fixture(*spec)))
        for initial, source in enumerate(images):
            before = corners(source)
            for target, expected in enumerate(images):
                goal = corners(expected)
                allowed = [name for name, steps in PLANS.items() if steps or before == goal]
                trials = {}
                for arm, policy, transitions in (("reference", "reference", {}),
                                                  ("learned", frozen["policy"], model),
                                                  ("swapped", frozen["policy"], swapped)):
                    matches = {p: predict(before, PLANS[p], transitions) == goal for p in allowed} if transitions else {}
                    plan = previous.choose(allowed, matches, policy)
                    encoded = apply_plan(source, PLANS[plan])
                    with Image.open(BytesIO(encoded)) as actual:
                        passed = (actual.format == "PNG" and actual.mode == expected.mode and
                                  actual.size == expected.size and actual.tobytes() == expected.tobytes())
                    trials[arm] = {"plan": plan, "passed": passed}
                cases.append({"seed": spec[0], "initial": initial, "target": target, "trials": trials})
    scores = {arm: sum(c["trials"][arm]["passed"] for c in cases) for arm in ("reference", "learned", "swapped")}
    losses = sum(c["trials"]["reference"]["passed"] and not c["trials"]["learned"]["passed"] for c in cases)
    return {"model_sha256": previous.source_hash(MODEL), "scores": scores, "paired_regressions": losses,
            "criterion_met": scores["learned"] > max(scores["reference"], scores["swapped"]) and losses == 0,
            "cases": cases}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("stage", choices=("train", "evaluate"))
    cli.add_argument("--output", type=Path, default=REPORT)
    args = cli.parse_args()
    if args.stage == "train":
        result = train()
        path = MODEL
    else:
        frozen = json.loads(MODEL.read_bytes())
        if json.loads(json.dumps(train())) != frozen:
            raise ValueError("Le rejeu d’apprentissage diverge du gel.")
        result = evaluate(frozen)
        path = args.output
    serialized = json.dumps(result, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise ValueError(f"Le résultat diverge du fichier existant {path}.")
    else:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    print(result.get("scores", result.get("model")))


if __name__ == "__main__":
    main()
