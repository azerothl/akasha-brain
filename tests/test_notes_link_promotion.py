import shutil

import pytest

from akasha_brain.experience import transaction
from akasha_brain.notes_link_promotion import NotesLinkPromotion, digest, disposable_signer, verify_signature
from akasha_brain.planning import ENVIRONMENT
from bench.run_notes_link_comparison import compile_graphs
from bench.run_notes_link_promotion import verify_chain


def proof(graph_id, sandbox_id, outcome="shared"):
    return {"verified": True, "graph_id": graph_id, "sandbox_id": sandbox_id, "outcome_sha256": outcome}


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="OpenSSH indisponible")
def test_signed_promotion_refuses_incomplete_divergent_and_tampered_proofs(tmp_path):
    with disposable_signer() as (public, sign):
        registry = NotesLinkPromotion(tmp_path / "registry.sqlite", "cycle", compile_graphs()[2], "freeze", "before", public)
        registry.initialize()
        with pytest.raises(RuntimeError, match="paliers"):
            registry.prepare("promote")
        assert registry.limited_route(ENVIRONMENT, eligible=True) == registry.parent
        registry.record_trial("replay", proof(registry.candidate, "one"))
        registry.record_trial("shadow_parent", proof(registry.parent, "two"))
        with pytest.raises(RuntimeError, match="divergent"):
            registry.record_trial("shadow_candidate", proof(registry.candidate, "three", "different"))
        with pytest.raises(RuntimeError, match="ordre"):
            registry.record_trial("shadow_candidate", proof(registry.candidate, "two"))
        registry.record_trial("shadow_candidate", proof(registry.candidate, "three"))
        assert registry.limited_route("another-project", eligible=True) == registry.parent
        assert registry.limited_route(ENVIRONMENT, eligible=True) == registry.candidate
        assert registry.limited_route(ENVIRONMENT, eligible=True) == registry.parent
        registry.record_trial("limited", proof(registry.candidate, "four"))
        document = registry.prepare("promote")
        tampered = {**document, "freeze_sha256": "different"}
        signature = sign(document)
        with pytest.raises(RuntimeError, match="Signature Ed25519 invalide"):
            registry.apply(tampered, signature)
        with pytest.raises(RuntimeError, match="état du registre"):
            registry.apply(tampered, sign(tampered))
        assert registry.active() == registry.parent
        registry.apply(document, signature)
        assert registry.active() == registry.candidate
        rollback = registry.prepare("rollback")
        rollback_signature = sign(rollback)
        registry.apply(rollback, rollback_signature)

    assert registry.active() == registry.parent
    assert verify_signature(document, signature, public)
    assert verify_signature(rollback, rollback_signature, public)
    assert verify_chain(registry.path)[-2:] == ["promote", "rollback"]


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="OpenSSH indisponible")
def test_active_monitor_resets_streak_and_rolls_back_once_on_verified_threshold(tmp_path):
    graphs = compile_graphs()[2]
    with disposable_signer() as (public, sign):
        registry = NotesLinkPromotion(tmp_path / "monitor.sqlite", "cycle", graphs, "freeze", "before", public,
                                      max_consecutive_failures=1)
        registry.initialize()
        registry.record_trial("replay", proof(registry.candidate, "one"))
        registry.record_trial("shadow_parent", proof(registry.parent, "two"))
        registry.record_trial("shadow_candidate", proof(registry.candidate, "three"))
        registry.limited_route(ENVIRONMENT, eligible=True)
        registry.record_trial("limited", proof(registry.candidate, "four"))
        promotion = registry.prepare("promote")
        promotion_signature = sign(promotion)
        registry.apply(promotion, promotion_signature)
        assert promotion["monitor"] == {"max_consecutive_failures": 1}

        wrong_policy = NotesLinkPromotion(registry.path, "cycle", graphs, "freeze", "before", public)
        with pytest.raises(RuntimeError, match="seuil"):
            wrong_policy.active()

        def report_for(run_id: str, *, healthy: bool = False) -> dict:
            return {
                "graph": graphs["candidate"], "status": "passed" if healthy else "failed",
                "sandbox_id": run_id, "sandbox_stopped": True, "experience_record_id": run_id,
                "isolation": {"guest_no_default_route": True}, "accepted_attempt": 1, "wall_s": 1.0,
                "trace": [
                    {"id": "generate_diff", "authorization": "allowed", "result": {
                        "diff_applied": True, "git_apply_check": True, "guest_sha256_verified": True,
                        "matches_desktop_protocol": True,
                    }},
                    {"id": "verify", "authorization": "allowed",
                     "result": {"passed": 4, "pytest_exit": 0, "sqlite_verifier_exit": 0}},
                    {"id": "verify_desktop", "authorization": "allowed", "result": {"guest_exit_code": 0x471F}},
                ],
            }

        def observe(report: dict, *, signer=sign) -> dict | None:
            def execute(selected):
                assert selected == registry.candidate
                return report

            return registry.run_active(execute, sign=signer)[1]

        first = report_for("first")
        with pytest.raises(RuntimeError, match="signataire"):
            observe(first, signer=None)
        assert observe(first)["consecutive_failures"] == 1
        assert observe(first) is None
        assert observe(report_for("healthy", healthy=True))["consecutive_failures"] == 0
        assert observe(report_for("next"))["consecutive_failures"] == 1
        assert registry.active() == registry.candidate

        crossing = report_for("crossing")
        with pytest.raises(RuntimeError, match="Signature"):
            observe(crossing, signer=lambda _: promotion_signature)
        with transaction(registry.path) as db:
            assert db.execute("SELECT run_id FROM link_observations ORDER BY position").fetchall() == [
                ("first",), ("healthy",), ("next",)]
        assert registry.active() == registry.candidate

        observation = observe(crossing)
        rollback = observation["rollback"]
        assert observation["consecutive_failures"] == 2
        assert rollback["document"]["automatic_trigger"]["observation_sha256"] == digest(observation["proof"])
        assert rollback["document"]["previous_decision_sha256"] == digest({
            "document": promotion, "signature": promotion_signature})
        assert registry.run_active(lambda selected: {"selected": selected}) == ({"selected": registry.parent}, None)

    assert registry.active() == registry.parent
    assert verify_signature(rollback["document"], rollback["signature"], public)
    assert verify_chain(registry.path)[-5:] == ["link_observed"] * 4 + ["rollback"]
