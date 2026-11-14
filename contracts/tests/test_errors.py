"""Taxonomie d'erreurs : unicité des codes, familles conformes à la spec."""

from akasha_contracts.errors import FAMILY, AkashaError, ErrorCode

SPEC_FAMILIES = {"contrat", "capacité", "permission", "ressource",
                 "environnement", "délai", "incertitude"}


def test_codes_uniques():
    assert len({c.value for c in ErrorCode}) == len(list(ErrorCode))


def test_familles_couvertes_et_conformes():
    assert set(FAMILY.values()) == SPEC_FAMILIES
    assert set(FAMILY) == set(ErrorCode)


def test_as_dict_stable():
    err = AkashaError(ErrorCode.APPROVAL_REQUIRED, "Approbation requise.")
    assert err.as_dict() == {
        "code": "approval_required",
        "family": "permission",
        "message": "Approbation requise.",
        "details": {},
    }
