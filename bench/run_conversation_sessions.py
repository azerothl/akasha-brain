"""Exerce le bureau Windows, la réouverture et le temps d'ouverture des sessions."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tkinter as tk
from tkinter import font, ttk
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from akasha_brain.desktop import Desktop
from akasha_brain.desktop_sessions import ConversationWorkspace
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.memory import NOTES_SCOPE
from akasha_brain.memory_backup import archive_path, backup, restore
from akasha_brain.memory_store import MemoryStore
from akasha_brain.project_check import inspect_project
from akasha_brain.retention import load_policy

CANARY = "AKASHA_G1_TEST_9ec22425c0f749f0"
BACKUP_FACT = {"suite": "synthetic", "passed": True}


def desktop_style(window):
    family = "Inter" if "Inter" in font.families(window) else "Segoe UI"
    Desktop.styles(SimpleNamespace(root=window, family=family))


def verify_storage(root, witness=CANARY):
    representations = (witness.encode(), witness.encode("utf-16le"), sha256(witness.encode()).hexdigest().encode(),
                       sha256(witness.encode()).digest())
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert all(canary not in data for canary in representations), "Le stockage a conservé le témoin."


def desktop(root, workspace):
    return Desktop(root, NotesTasks(workspace / "runs", None, None, False)).conversation


def bind_project(pane, project):
    with patch("akasha_brain.desktop_conversation.filedialog.askdirectory", return_value=str(project)):
        assert pane.choose_project()


def create_sessions(root):
    project = root / "project"
    project.mkdir()
    (project / "check.py").write_text("assert True\n", encoding="utf-8")
    window = tk.Tk()
    window.withdraw()
    try:
        workspace = desktop(window, root)
        first = workspace.current
        bind_project(first, project)
        first.summary_choice.invoke()
        first.show_inspection(inspect_project(project))
        first.entry.insert(0, CANARY)
        first.send()
        assert CANARY in first.transcript.get("1.0", "end")
        workspace.new()
        second = workspace.current
        bind_project(second, project)
        second.summary_choice.invoke()
        second.summary_choice.invoke()
        (project / "check.py").unlink()
        second.show_inspection(inspect_project(project))
        assert CANARY not in second.transcript.get("1.0", "end")
        assert second.session_record.title == "Session 2"
        assert len(first.session_record.facts) == 2
    finally:
        window.destroy()
    verify_storage(root)


def reopen_sessions(root):
    window = tk.Tk()
    window.withdraw()
    try:
        workspace = desktop(window, root)
        first, second = (entry[0] for entry in workspace.entries)
        assert workspace.current.session_record.id == second
        assert workspace.current.summary_detail.get() is False
        workspace.refresh()
        workspace.menu.invoke(0)
        assert workspace.current.session_record.id == first
        assert workspace.current.project == root / "project"
        assert workspace.current.summary_detail.get() is True
        assert "script Python" in workspace.current.session_observation.cget("text")
        assert CANARY not in workspace.current.transcript.get("1.0", "end")
        workspace.menu.invoke(1)
        assert workspace.current.session_record.id == second
        assert workspace.current.project == root / "project"
        assert workspace.current.summary_detail.get() is False
        assert "aucun test repéré" in workspace.current.session_observation.cget("text")
    finally:
        window.destroy()
    verify_storage(root)


def replay_restart_with_backup(root):
    command = [sys.executable, "-B", "-X", "utf8", "-m", "bench.run_conversation_sessions",
               "--workspace", str(root), "--stage"]
    subprocess.run([*command, "create"], check=True)
    memory = MemoryStore(root / "runs/global-memory.sqlite")
    memory.initialize()
    with memory.access() as (control, db):
        item = memory.save(control, db, kind="fact", scope=NOTES_SCOPE, payload=BACKUP_FACT,
                           now=memory.clock(), policy=load_policy())
    saved = backup(memory)
    assert saved["status"] == "backed_up" and saved["items"] == 1
    archive = archive_path(memory, saved["id"])
    archive_sha256 = sha256(archive.read_bytes()).digest()
    verify_storage(root)
    subprocess.run([*command, "reopen"], check=True)
    assert sha256(archive.read_bytes()).digest() == archive_sha256
    with memory.access() as (_, db):
        # Simule la perte d'un fait du banc en préservant l'identité du stockage jetable.
        assert db.execute("DELETE FROM memory_items WHERE id = ?", (item,)).rowcount == 1
    assert restore(memory, saved["id"]) == {"status": "restored", "added": 1, "erased_omitted": 0}
    with memory.access() as (_, db):
        restored, = db.execute("SELECT payload FROM memory_items").fetchall()
        assert json.loads(restored["payload"]) == BACKUP_FACT
    verify_storage(root)


def reference_pane(revision):
    commit = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
                                     text=True).strip()

    def load(name):
        relative = f"akasha_brain/{name}.py"
        source = subprocess.check_output(["git", "show", f"{commit}:{relative}"])
        module = ModuleType(f"akasha_brain._reference_{name}")
        module.__file__ = str(Path(relative).resolve())
        sys.modules[module.__name__] = module
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        return module

    reference = load("desktop_conversation")
    reference.load_conversation_catalog = load("conversation_planning").load_conversation_catalog
    return commit, reference.ConversationPane


def measure(root, baseline_ms, samples, *, reference=None):
    window = tk.Tk()
    window.withdraw()
    desktop_style(window)
    tasks = NotesTasks(root / "runs", None, None, False)
    results = []
    baselines = []

    def timed(constructor, **options):
        frame = ttk.Frame(window)
        before = perf_counter()
        view = constructor(frame, None, None, None, None, tasks, review_prepared=None, **options)
        window.update_idletasks()
        elapsed = (perf_counter() - before) * 1000
        if isinstance(view, ConversationWorkspace):
            assert len(view.current.session_record.facts) == 2
        frame.destroy()
        return elapsed

    try:
        for index in range(samples + 1):
            baseline = None
            if reference and index % 2 == 0:
                baseline = timed(reference[1], project=root / "project")
            elapsed = timed(ConversationWorkspace, project=None)
            if reference and index % 2 == 1:
                baseline = timed(reference[1], project=root / "project")
            if index:
                results.append(elapsed)
                if baseline is not None:
                    baselines.append(baseline)
    finally:
        window.destroy()
    if reference:
        baseline_ms = round(median(baselines), 3)
    threshold = min(2 * baseline_ms, 500)
    timing = {"baseline_ms": baseline_ms, "threshold_ms": threshold, "samples": samples, "remembered_facts": 2,
              "profile": "Windows Tk avec le thème du bureau",
              "median_ms": round(median(results), 3), "passed": median(results) <= threshold}
    if reference:
        timing.update(baseline_commit=reference[0], alternating_pairs=True)
    return timing


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    baseline = cli.add_mutually_exclusive_group()
    baseline.add_argument("--baseline-ms", type=float)
    baseline.add_argument("--baseline-ref", help="Révision Git de référence à mesurer dans le même processus Tk")
    cli.add_argument("--output", type=Path)
    cli.add_argument("--stage", choices=("create", "reopen"))
    cli.add_argument("--workspace", type=Path)
    args = cli.parse_args()
    if args.stage:
        check = create_sessions if args.stage == "create" else reopen_sessions
        check(args.workspace.resolve(strict=True))
        return
    if args.output is None or (args.baseline_ref is None and (args.baseline_ms is None or args.baseline_ms <= 0)):
        cli.error("--output et une référence positive par --baseline-ms ou --baseline-ref sont requis")
    reference = reference_pane(args.baseline_ref) if args.baseline_ref else None
    with TemporaryDirectory(prefix="akasha-conversation-session-") as directory:
        workspace = Path(directory).resolve()
        replay_restart_with_backup(workspace)
        timing = measure(workspace, args.baseline_ms, samples=20, reference=reference)
        verify_storage(workspace)
    result = {"status": "passed" if timing["passed"] else "failed", "two_sessions_same_project": True,
              "process_restart_verified": True, "structured_facts_restored": True, "synthetic_secret_absent": True,
              "controlled_backup": {"encrypted_items": 1, "checked_before_and_after_restart": True,
                                    "synthetic_item_restored_and_verified": True},
              "timing": timing}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return int(not timing["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
