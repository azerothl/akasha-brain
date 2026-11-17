from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from akasha_brain.conversation_sessions import SessionStore
from akasha_brain.conversation_vault import SessionVault, admit_secret
from akasha_brain.memory_store import MemoryRefusal
from akasha_brain.project_audit import verify


class TestKeyStore:
    __test__ = False

    def __init__(self):
        self.values = {}
        self.reads = []

    def put(self, handle, value):
        self.values[handle] = bytearray(value)

    def get(self, handle):
        self.reads.append(handle)
        return bytearray(self.values[handle])

    def erase(self, handle):
        self.values.pop(handle, None)


def test_vault_classifies_only_single_supported_or_labeled_secrets():
    assert admit_secret("Vérifie les tests de ce projet") is None
    assert admit_secret("Clé API : valeur-opaque") == bytearray(b"valeur-opaque")
    assert admit_secret("ghp_ABCDEFGHIJKLMNOP") == bytearray(b"ghp_ABCDEFGHIJKLMNOP")
    for request in ("Passe la clé API : valeur-opaque au modèle",
                    "Envoie ghp_ABCDEFGHIJKLMNOP", "Clé API : valeur et précisions",
                    "-----BEGIN PRIVATE KEY-----\nclé\n-----END PRIVATE KEY-----"):
        with pytest.raises(ValueError, match="seule clé"):
            admit_secret(request)


def test_vault_authorizes_scoped_resolution_and_erases_without_storing_secret(tmp_path):
    sessions = SessionStore(tmp_path / "sessions.sqlite")
    first, second = sessions.create(), sessions.create()
    backend = TestKeyStore()
    vault = SessionVault(tmp_path, sessions, keystore=lambda: backend)
    witness = b"synthetic_g2_secret"
    source = bytearray(witness)
    handle = vault.seal(first, source)
    assert not any(source)
    assert vault.handles(first) == (handle,) and vault.handles(second) == ()

    with pytest.raises(MemoryRefusal, match="session"):
        with vault.resolve(second, handle, approve=lambda: pytest.fail("Un accès hors périmètre a été proposé")):
            pytest.fail("Le coffre a renvoyé une clé hors périmètre")
    with pytest.raises(MemoryRefusal, match="refusée"):
        with vault.resolve(first, handle, approve=lambda: False):
            pytest.fail("Le coffre a ignoré le refus")
    assert not backend.reads
    with vault.resolve(first, handle, approve=lambda: True) as value:
        assert value.readonly and bytes(value) == witness
    assert bytes(value) == bytes(len(witness))
    assert backend.reads == [handle]

    vault.erase(first, handle)
    assert not vault.handles(first) and handle not in backend.values
    audit = verify(tmp_path / "akasha-audit.sqlite")
    assert audit == {"status": "passed", "entries_verified": 5}
    for file in tmp_path.iterdir():
        content = file.read_bytes()
        assert witness not in content and sha256(witness).hexdigest().encode() not in content


def test_expired_secret_is_denied_and_swept(tmp_path):
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    sessions = SessionStore(tmp_path / "sessions.sqlite", clock=lambda: now)
    session = sessions.create()
    backend = TestKeyStore()
    vault = SessionVault(tmp_path, sessions, keystore=lambda: backend)
    handle = vault.seal(session, bytearray(b"expiring_secret"))
    now += timedelta(days=31)
    with pytest.raises(MemoryRefusal, match="expiré"):
        with vault.resolve(session, handle, approve=lambda: True):
            pytest.fail("Le coffre a libéré une clé expirée")
    assert not vault.handles(session)
    assert not backend.values
