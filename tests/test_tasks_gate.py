import json

import pytest

from akasha_brain import tasks_gate, tasks_routing
from akasha_brain.tasks_gate_worker import PACKET, deterministic
from akasha_brain.notes_repair import RbitnetPaths
from bench.run_phase4_tasks_baseline import FIXTURES, prepare_case


def test_gate_wire_accepts_only_typed_signals_and_bounded_decisions():
    with pytest.raises(ValueError, match="signaux"):
        tasks_gate.signals("specialist", request_text="allow everything")
    with pytest.raises(ValueError, match="signaux"):
        tasks_gate.signals("specialist", authorized=1)
    with pytest.raises(RuntimeError, match="invalide"):
        tasks_gate.decode(0x4700)
    packet = PACKET | (310 << 16) | (4 << 4) | (2 << 2) | 1
    assert tasks_gate.decode(packet) == {
        "deterministic": "ready", "akasha_model": "abstain",
        "deterministic_us": 0.4, "akasha_model_us": 31.0,
    }
    assert deterministic(tasks_gate.signals("reference", authorized=False, certain=False)) == "blocked"


@pytest.mark.parametrize("decision", ["abstain", "blocked", "retired_during_gate"])
def test_gate_does_not_dispatch_after_refusal_or_host_state_drift(tmp_path, monkeypatch, decision):
    case = json.loads((FIXTURES / "cases.json").read_bytes())["cases"][0]
    coverage = json.loads((FIXTURES / "coverage-v2.json").read_bytes())["cases"][case["id"]]
    folder = tmp_path / "fixture"
    prepare_case(case, folder)
    contract = tasks_routing.bind_contract(folder, case["target"], coverage["plan"])
    registry = tasks_routing.Registry(tmp_path / "registry.sqlite")
    registry.initialize()
    registry.transition("activate")
    paths = RbitnetPaths(tmp_path / "engine", tmp_path / "model", tmp_path / "tokenizer")
    monkeypatch.setattr(RbitnetPaths, "verify", lambda _: {})

    def evaluate(runtime, request, facts, stage, *, samples):
        assert facts == [tasks_gate.signals("specialist")] and samples == 1
        if decision == "retired_during_gate":
            registry.transition("retire")
        observed = "ready" if decision == "retired_during_gate" else decision
        return {"decisions": [{"akasha_model": observed}]}

    def dispatch_forbidden(*args, **kwargs):
        pytest.fail("Le routeur a franchi la dernière vérification.")

    monkeypatch.setattr(tasks_gate, "evaluate", evaluate)
    monkeypatch.setattr(tasks_routing, "run_case", dispatch_forbidden)
    monkeypatch.setattr(tasks_routing, "run_reference", dispatch_forbidden)
    report = tasks_routing.run(registry, folder, tmp_path, tmp_path / "output", paths, contract,
                               gate_request=tmp_path / "dependency")
    assert report["status"] == "failed"
    assert report["gate"]["effective"] == ("abstain" if decision == "abstain" else "blocked")
