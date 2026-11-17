from dataclasses import replace
import shutil
from uuid import uuid4

import pytest

from akasha_brain.bounded_evolution import BoundedEvolution, Observation, Policy, SandboxScope, STAGES
from akasha_brain.integrated_evolution import IntegratedEvolution
from akasha_brain.notes_link_promotion import disposable_signer
from akasha_brain.planning import ENVIRONMENT


def new_scope():
    return SandboxScope(str(uuid4()), ENVIRONMENT, "R1", True, True)


def policy():
    return Policy("route", "parent", "candidate", "a" * 64, ("repair",), ("control",), "repair", 1000)


def sample(scope, case, version, *, verified=True, input_hash="b" * 64):
    return Observation(scope.sandbox_id, case, version, input_hash, "c" * 64, True, verified, 50, 900)


def unexpected_sign(_):
    pytest.fail("Aucune activation n'est attendue.")


@pytest.mark.parametrize("same_input", (True, False))
def test_replay_requires_gain_on_the_same_input(tmp_path, same_input):
    rules = policy()
    cycle = BoundedEvolution(tmp_path / "cycle.sqlite", str(uuid4()), rules, "unused-before-promotion")
    cycle.initialize()
    scope = new_scope()
    assert not cycle.reserve("shadow", scope)
    assert cycle.reserve("replay", scope)
    parent = sample(scope, "repair", rules.parent, verified=same_input)
    candidate = sample(scope, "repair", rules.candidate, input_hash="b" * 64 if same_input else "d" * 64)

    assert not cycle.complete_stage("replay", scope, (parent, candidate), unexpected_sign)["qualified"]
    assert not cycle.complete_stage("replay", scope, (parent, candidate), unexpected_sign)["qualified"]
    corrected = (replace(parent, verified=False), replace(candidate, input_sha256=parent.input_sha256))
    with pytest.raises(RuntimeError, match="consommé sa tentative"):
        cycle.complete_stage("replay", scope, corrected, unexpected_sign)
    assert cycle.active() == rules.parent
    assert not cycle.reserve("shadow", new_scope())


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="Signature Ed25519 avec OpenSSH")
def test_signed_activation_and_rollback_survive_reopen(tmp_path):
    rules = policy()
    path = tmp_path / "cycle.sqlite"
    identifier = str(uuid4())
    with disposable_signer() as (public_key, sign):
        cycle = BoundedEvolution(path, identifier, rules, public_key)
        cycle.initialize()
        for stage in STAGES:
            scope = new_scope()
            assert not cycle.reserve(stage, replace(scope, risk_class="R3"))
            assert cycle.reserve(stage, scope)
            assert not cycle.reserve(stage, scope)
            case, = rules.cases(stage)
            candidate = sample(scope, case, rules.candidate)
            parent = sample(scope, case, rules.parent, verified=stage != "replay")
            receipts = (candidate,) if stage == "limited" else (parent, candidate)
            assert cycle.complete_stage(stage, scope, receipts, sign)["qualified"]
        reopened = BoundedEvolution(path, identifier, rules, public_key)
        live = new_scope()
        assert reopened.select(live, "repair") == rules.candidate
        assert reopened.select(live, "control") == rules.parent
        with pytest.raises(PermissionError):
            reopened.select(replace(live, synthetic=False), "repair")
        delayed = replace(sample(live, "repair", rules.candidate), decision_us=1001)
        result = reopened.observe(live, delayed, sign)
        assert result["alerts"] == ["decision_latency"]
        assert result["active"] == rules.parent
        assert reopened.observe(live, delayed, sign)["duplicate"]
    assert BoundedEvolution(path, identifier, rules, public_key).active() == rules.parent


def test_batch_binds_each_receipt_to_its_authorized_sandbox(tmp_path):
    rules = replace(policy(), family="skill", min_wall_savings_ms=100)
    cycle = BoundedEvolution(tmp_path / "cycle.sqlite", str(uuid4()), rules, "unused-before-promotion")
    cycle.initialize()
    batch = str(uuid4())
    assert cycle.reserve_batch("replay", batch)
    parent, candidate = new_scope(), new_scope()
    assert cycle.admit_trial("replay", batch, parent, "repair", rules.parent)
    assert not cycle.admit_trial("replay", batch, parent, "repair", rules.candidate)
    assert not cycle.admit_trial("replay", batch, replace(candidate, risk_class="R2"), "repair", rules.candidate)
    assert cycle.admit_trial("replay", batch, candidate, "repair", rules.candidate)
    previous = sample(parent, "repair", rules.parent)
    faster = replace(sample(candidate, "repair", rules.candidate), wall_ms=600)
    with pytest.raises(PermissionError, match="bacs admis"):
        cycle.complete_batch("replay", batch, (previous, replace(faster, sandbox_id=new_scope().sandbox_id)), unexpected_sign)
    result = cycle.complete_batch("replay", batch, (previous, faster), unexpected_sign)
    assert result["qualified"]
    assert result["cases"]["repair"]["wall_delta_ms"] == -300
    assert cycle.active() == rules.parent


def test_speed_cannot_qualify_a_different_verified_result(tmp_path):
    rules = replace(policy(), family="skill", min_wall_savings_ms=100)
    cycle = BoundedEvolution(tmp_path / "cycle.sqlite", str(uuid4()), rules, "unused-before-promotion")
    cycle.initialize()
    scope = new_scope()
    assert cycle.reserve("replay", scope)
    parent = sample(scope, "repair", rules.parent)
    candidate = replace(sample(scope, "repair", rules.candidate), wall_ms=600, result_sha256="f" * 64)
    assert not cycle.complete_stage("replay", scope, (parent, candidate), unexpected_sign)["qualified"]


def test_limited_exposure_requires_the_input_measured_in_replay(tmp_path):
    rules = policy()
    cycle = BoundedEvolution(tmp_path / "cycle.sqlite", str(uuid4()), rules, "unused-before-promotion")
    cycle.initialize()
    for stage in STAGES[:-1]:
        scope = new_scope()
        assert cycle.reserve(stage, scope)
        case, = rules.cases(stage)
        receipts = (sample(scope, case, rules.parent, verified=stage == "shadow"),
                    sample(scope, case, rules.candidate))
        assert cycle.complete_stage(stage, scope, receipts, unexpected_sign)["qualified"]
    limited = new_scope()
    assert cycle.reserve("limited", limited)
    result = cycle.complete_stage("limited", limited,
                                  (sample(limited, "repair", rules.candidate, input_hash="e" * 64),),
                                  unexpected_sign)
    assert not result["qualified"]
    assert not result["cases"]["repair"]["same_input"]
    assert cycle.active() == rules.parent


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="Signature Ed25519 avec OpenSSH")
def test_integrated_rollback_restores_all_effective_parents(tmp_path):
    with disposable_signer() as (public_key, sign):
        cycles = {
            family: BoundedEvolution(tmp_path / f"{family}.sqlite", str(uuid4()),
                                    replace(policy(), family=family), public_key)
            for family in ("route", "skill", "memory")
        }
        for cycle in cycles.values():
            cycle.initialize()
        path = tmp_path / "integrated.sqlite"
        combined = IntegratedEvolution(path, cycles)
        combined.initialize()
        for family in ("route", "skill"):
            for stage in STAGES:
                scope = new_scope()
                with combined.qualification(family) as cycle:
                    assert cycle.reserve(stage, scope)
                    case, = cycle.policy.cases(stage)
                    candidate = sample(scope, case, "candidate")
                    parent = sample(scope, case, "parent", verified=stage != "replay")
                    receipts = (candidate,) if stage == "limited" else (parent, candidate)
                    cycle.complete_stage(stage, scope, receipts, sign)
        assert combined.status()["effective"] == {"route": "candidate", "skill": "candidate", "memory": "parent"}
        scope = new_scope()
        failed = replace(sample(scope, "repair", "candidate", verified=False), mismatches=("sqlite.row_count",))
        result = combined.observe("route", scope, failed, sign)
        assert result["autonomy_phase"] == 3
        assert result["signed_active"]["skill"] == "candidate"
        assert combined.select("skill", scope, "repair") == "parent"
        with pytest.raises(PermissionError):
            with combined.qualification("memory"):
                pytest.fail("L'autonomie de phase 6 est suspendue.")
    opened = IntegratedEvolution(path, cycles)
    assert opened.status()["autonomy_phase"] == 3
    assert set(opened.status()["rollback_proofs"]) == {"route"}


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="Signature Ed25519 avec OpenSSH")
def test_integrated_operator_rollback_is_signed_durable_and_stops_qualification(tmp_path):
    with disposable_signer() as (public_key, sign):
        rules = policy()
        cycle = BoundedEvolution(tmp_path / "route.sqlite", str(uuid4()), rules, public_key)
        cycle.initialize()
        path = tmp_path / "integrated.sqlite"
        manager = IntegratedEvolution(path, {"route": cycle})
        manager.initialize()
        for stage in STAGES:
            scope = new_scope()
            assert cycle.reserve(stage, scope)
            case, = rules.cases(stage)
            parent = sample(scope, case, rules.parent, verified=stage != "replay")
            candidate = sample(scope, case, rules.candidate)
            receipts = (candidate,) if stage == "limited" else (parent, candidate)
            assert cycle.complete_stage(stage, scope, receipts, sign)["qualified"]

        with pytest.raises(RuntimeError, match="Signature"):
            manager.request_rollback(lambda _: "invalid")
        assert manager.status()["effective"] == {"route": rules.candidate}
        assert manager.request_rollback(sign) == manager.request_rollback(unexpected_sign)

    reopened = IntegratedEvolution(path, {"route": cycle})
    assert reopened.status()["autonomy_phase"] == 3
    assert reopened.status()["effective"] == {"route": rules.parent}
    assert set(reopened.status()["rollback_proofs"]) == {"operator"}
    with pytest.raises(PermissionError):
        with reopened.qualification("route"):
            pytest.fail("Une promotion a été admise après le retour demandé.")
