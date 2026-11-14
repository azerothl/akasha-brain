"""Autorisation : permissions accordées, refus et échecs typés (spec §13.5-13.7)."""

from akasha_contracts import authorize, escalate
from akasha_contracts.errors import ErrorCode


def test_r0_observation_autorisee():
    assert authorize({"risk_class": "R0"}) is None


def test_r1_autorisee_si_confinement_verifie():
    assert authorize({"risk_class": "R1", "confinement_verified": True}) is None


def test_r1_refusee_sans_confinement():
    err = authorize({"risk_class": "R1", "confinement_verified": False})
    assert err is not None and err.code == ErrorCode.PERMISSION_DENIED


def test_r2_exige_approbation_par_defaut():
    err = authorize({"risk_class": "R2"})
    assert err is not None and err.code == ErrorCode.APPROVAL_REQUIRED
    assert authorize({"risk_class": "R2", "human_approval": True}) is None


def test_sous_specifie_bloque_avant_clarification():
    err = authorize({"risk_class": "R2", "underspecified": True})
    assert err is not None and err.code == ErrorCode.NEEDS_CLARIFICATION


def test_r3_exige_approbation_humaine():
    err = authorize({"risk_class": "R3"})
    assert err is not None and err.code == ErrorCode.APPROVAL_REQUIRED
    assert authorize({"risk_class": "R3", "human_approval": True}) is None


def test_classe_inconnue_vaut_r3():
    for action in ({}, {"risk_class": "R9"}, {"risk_class": None}):
        err = authorize(action)
        assert err is not None and err.code == ErrorCode.APPROVAL_REQUIRED


def test_destructive_hint_escalade():
    assert escalate("R0", True) == "R2"
    assert escalate("R1", True) == "R2"
    assert escalate("R2", True) == "R2"
    assert escalate(None, False) == "R3"
