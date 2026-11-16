import shutil

import pytest

from akasha_brain.notes_link_promotion import NotesLinkPromotion, disposable_signer, verify_signature
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
