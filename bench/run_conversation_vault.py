"""Vérifie le coffre Windows et la persistance des seuls handles."""

import argparse
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tkinter as tk
from uuid import UUID

from akasha_brain.conversation_sessions import SessionId, SessionStore
from akasha_brain.conversation_vault import SessionVault
from akasha_brain.desktop import Desktop
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.memory import NOTES_SCOPE
from akasha_brain.memory_backup import backup
from akasha_brain.memory_store import MemoryRefusal, MemoryStore
from akasha_brain.project_audit import verify
from akasha_brain.retention import load_policy
from akasha_brain.vault_windows import SecretMissing, WindowsKeyStore
from bench.run_conversation_sessions import verify_storage

WITNESS = "akasha_g2_synthetic_9e1622c65e064f53"
MEMORY_PAYLOAD = {"suite": "synthetic", "passed": True}


def seal_on_desktop(root):
    window = tk.Tk()
    window.withdraw()
    try:
        pane = Desktop(window, NotesTasks(root / "runs", None, None, False)).conversation.current
        pane.entry.insert(0, f"Clé API : {WITNESS}")
        pane.send()
        handles = pane.session_vault().handles(pane.session_record.id)
        assert len(handles) == 1
        transcript = pane.transcript.get("1.0", "end")
        assert str(handles[0]) in transcript and WITNESS not in transcript
        assert pane.intent_job is None
        (root / "references.json").write_text(json.dumps({"session": str(pane.session_record.id),
                                                           "handle": str(handles[0])}), encoding="utf-8")
    finally:
        window.destroy()


def references(root):
    record = json.loads((root / "references.json").read_text(encoding="utf-8"))
    return SessionId(UUID(record["session"])), UUID(record["handle"])


def resolve_after_restart(root):
    sessions = SessionStore(root / "runs/conversation-sessions.sqlite")
    vault = SessionVault(root / "runs", sessions)
    session, handle = references(root)
    other = sessions.create()
    assert vault.handles(session) == (handle,) and not vault.handles(other)
    for user, approval in ((session, False), (other, True)):
        try:
            with vault.resolve(user, handle, approve=lambda: approval):
                raise AssertionError("Le coffre a laissé passer un refus.")
        except MemoryRefusal as error:
            assert error.code == "permission_denied"
    with vault.resolve(session, handle, approve=lambda: True) as value:
        assert bytes(value) == WITNESS.encode()
    assert not any(value)
    vault.erase(session, handle)
    assert not vault.handles(session)
    try:
        WindowsKeyStore().get(handle)
    except SecretMissing:
        return
    raise AssertionError("L’entrée de test reste présente dans le coffre Windows.")


class MeasuredKeyStore(WindowsKeyStore):
    elapsed = 0.0

    def put(self, handle, secret):
        before = perf_counter()
        super().put(handle, secret)
        self.elapsed += perf_counter() - before

    def get(self, handle):
        before = perf_counter()
        value = super().get(handle)
        self.elapsed += perf_counter() - before
        return value


def save_fixture(memory, policy):
    with memory.access() as (control, db):
        return memory.save(control, db, kind="fact", scope=NOTES_SCOPE, payload=MEMORY_PAYLOAD,
                           now=memory.clock(), policy=policy)


def measure(root, memory, *, samples=20):
    sessions = SessionStore(root / "runs/conversation-sessions.sqlite")
    session = sessions.create()
    backend = MeasuredKeyStore()
    vault = SessionVault(root / "runs", sessions, keystore=lambda: backend)
    policy = load_policy()
    timings = {"memory_write_ms": [], "seal_ms": [], "seal_without_keystore_ms": [], "resolve_ms": []}
    for trial in range(samples + 1):
        before = perf_counter()
        save_fixture(memory, policy)
        baseline = perf_counter() - before
        backend.elapsed = 0.0
        before = perf_counter()
        handle = vault.seal(session, bytearray(WITNESS, "ascii"))
        seal = perf_counter() - before
        without_keystore = seal - backend.elapsed
        try:
            before = perf_counter()
            with vault.resolve(session, handle, approve=lambda: True) as value:
                assert len(value) == len(WITNESS)
            resolve = perf_counter() - before
        finally:
            vault.erase(session, handle)
        if trial:
            for name, value in zip(timings, (baseline, seal, without_keystore, resolve), strict=True):
                timings[name].append(value * 1_000)
    medians = {name: round(median(values), 3) for name, values in timings.items()}
    added = round(medians["seal_without_keystore_ms"] - medians["memory_write_ms"], 3)
    return {**medians, "samples": samples, "added_ms": added, "threshold_ms": 20, "passed": added <= 20}


def run(root):
    memory = MemoryStore(root / "runs/global-memory.sqlite")
    memory.initialize()
    save_fixture(memory, load_policy())
    python = [sys.executable, "-B", "-X", "utf8", "-m", "bench.run_conversation_vault"]
    try:
        subprocess.run([*python, "--stage", "seal", "--workspace", str(root)], check=True)
        saved = backup(memory)
        assert saved["status"] == "backed_up" and saved["items"] == 1
        verify_storage(root, WITNESS)
        subprocess.run([*python, "--stage", "reopen", "--workspace", str(root)], check=True)
        verify_storage(root, WITNESS)
        audit = verify(root / "runs/akasha-audit.sqlite")
        assert audit["status"] == "passed" and audit["entries_verified"] >= 5
        timing = measure(root, memory)
        verify_storage(root, WITNESS)
        return {"status": "passed" if timing["passed"] else "failed", "platform": "Windows",
                "desktop_substituted_handle": True, "restarted_process_resolved": True,
                "cross_session_and_denial_blocked": True, "os_entry_erased": True,
                "synthetic_secret_and_fingerprint_absent": True, "backup_items": saved["items"],
                "audit": audit, "timing": timing}
    finally:
        if (root / "references.json").is_file():
            WindowsKeyStore().erase(references(root)[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stage", choices=("seal", "reopen"))
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if args.stage:
        check = seal_on_desktop if args.stage == "seal" else resolve_after_restart
        check(args.workspace.resolve(strict=True))
        return 0
    if args.output is None:
        parser.error("--output est requis")
    with TemporaryDirectory(prefix="akasha-vault-g2-") as workspace:
        result = run(Path(workspace).resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
