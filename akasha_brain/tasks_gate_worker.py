"""Évalue les deux politiques dans le bac et restitue un paquet numérique borné."""

from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath
import sys
from time import perf_counter_ns
from zipfile import ZipFile

WHEEL = "akasha_model-0.3.0-py3-none-any.whl"
WHEEL_SHA256 = "c32a19ac01d26203a5a117bd67649dd442daa6695ccbc96aa983537b62cc188f"
VERSION = "0.3.0"
TOOLS = ("reference", "specialist")
STATUSES = {1: "ready", 2: "abstain", 3: "blocked"}
SIGNALS = {"tool", "authorized", "context", "capability", "certain", "risk", "budget",
           "confirmation_needed", "confirmation_given"}
PACKET = 0x50000000
TIMING_MAX = 4095
TIMING_UNIT_NS = 100
SAMPLES = 50


def validate(signals: dict) -> None:
    bools = SIGNALS - {"tool", "risk", "budget"}
    if (set(signals) != SIGNALS or signals["tool"] not in TOOLS
            or any(type(signals[key]) is not bool for key in bools)
            or type(signals["risk"]) is not int or signals["risk"] not in (0, 1)
            or (signals["budget"] is not None and type(signals["budget"]) is not int)):
        raise ValueError("La porte exige des signaux Tâches typés.")


def deterministic(signals: dict) -> str:
    denied = (not signals["authorized"] or not signals["context"] or not signals["capability"]
              or signals["risk"] != 0 or (signals["budget"] is not None and signals["budget"] <= 0)
              or (signals["confirmation_needed"] and not signals["confirmation_given"]))
    if denied:
        return "blocked"
    return "ready" if signals["certain"] else "abstain"


def path_a(signals: dict) -> str:
    from akasha_model import GateSignals, ScoreLevel, ScoreQuestion, ToolCallPlanner, ToolProposal, ToolSpec, evaluate_gate
    from akasha_model.primitives import score_result

    tools = {name: ToolSpec(name, required_capability="sandbox_cpu",
                            parameters={"type": "object", "additionalProperties": False}) for name in TOOLS}
    hard_blocked = deterministic({**signals, "certain": True}) == "blocked"
    # Une proposition ambiguë ne masque pas un refus fondé sur un signal hôte.
    probabilities = {name: float(name == signals["tool"]) if signals["certain"] or hard_blocked else 0.5
                     for name in TOOLS}
    question = ScoreQuestion("risk", "Classe hôte", (ScoreLevel("R1"), ScoreLevel("hors périmètre")))
    risk = score_result(question, {level: float(level == signals["risk"]) for level in (0, 1)})
    plan = evaluate_gate(
        tools, ToolProposal(signals["tool"], {}, probabilities),
        GateSignals(authorized=float(signals["authorized"]), sufficient_context=float(signals["context"]),
                    capability_present=float(signals["capability"]), confirmation_needed=float(signals["confirmation_needed"]),
                    confirmation_given=signals["confirmation_given"], budget_remaining=signals["budget"], risk=risk),
        planner=ToolCallPlanner(min_choice_probability=1.0, min_choice_confidence=1.0,
                                noul_threshold=1.0, max_risk_score=0.0),
    )
    if plan.status == "ready" and (plan.tool_name != signals["tool"] or plan.arguments != {}):
        raise RuntimeError("Le plan prêt a changé la proposition du système hôte.")
    return plan.status


def sample(policy, signals: dict, samples: int) -> tuple[int, int]:
    started = perf_counter_ns()
    decisions = [policy(signals) for _ in range(samples)]
    elapsed = perf_counter_ns() - started
    if len(set(decisions)) != 1:
        raise RuntimeError("La décision varie à signaux identiques.")
    code, = [number for number, status in STATUSES.items() if status == decisions[0]]
    ticks = min(TIMING_MAX, round(elapsed / (samples * TIMING_UNIT_NS)))
    return code, ticks


def install(wheel: Path, directory: Path) -> None:
    if sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
        raise ValueError("La roue ne correspond pas à l'empreinte épinglée.")
    directory.mkdir(parents=True)
    allowed = {"akasha_model", f"akasha_model-{VERSION}.dist-info"}
    with ZipFile(wheel) as archive:
        seen = set()
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or not path.parts or path.parts[0] not in allowed or ".." in path.parts
                    or ":" in entry.filename or "\\" in entry.filename or entry.filename.casefold() in seen):
                raise ValueError("Entrée de roue non admise.")
            seen.add(entry.filename.casefold())
        archive.extractall(directory)


def main() -> int:
    source = Path(__file__).resolve().parent
    tag, index = sys.argv[1], int(sys.argv[2])
    if len(tag) != 8 or any(char not in "0123456789abcdef" for char in tag) or index < 0:
        raise ValueError("Index ou identifiant du banc invalide.")
    packages = Path(os.environ["TEMP"]) / f"AkashaTasksGate-{tag}" / "packages"
    if index == 0:
        install(source / "wheels" / WHEEL, packages)
    sys.path.insert(0, str(packages))
    from akasha_model import __version__

    if version("akasha-model") != VERSION or __version__ != VERSION or "torch" in sys.modules:
        raise RuntimeError("Le bac exige la seule installation Path A épinglée.")
    request = json.loads((source / "signals.json").read_bytes())
    signals, samples = request["decisions"][index], request["samples"]
    if samples not in (1, SAMPLES):
        raise ValueError("Nombre d'échantillons inattendu.")
    validate(signals)
    if samples > 1:
        path_a(signals)
    baseline, baseline_ticks = sample(deterministic, signals, samples)
    candidate, candidate_ticks = sample(path_a, signals, samples)
    return PACKET | (candidate_ticks << 16) | (baseline_ticks << 4) | (candidate << 2) | baseline


if __name__ == "__main__":
    raise SystemExit(main())
