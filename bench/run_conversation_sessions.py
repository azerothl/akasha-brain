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
from tkinter import ttk
from unittest.mock import patch

from akasha_brain.desktop import Desktop
from akasha_brain.desktop_sessions import ConversationWorkspace
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.project_check import inspect_project

CANARY = "AKASHA_G1_TEST_9ec22425c0f749f0"


def verify_storage(root):
    representations = (CANARY.encode(), CANARY.encode("utf-16le"), sha256(CANARY.encode()).hexdigest().encode(),
                       sha256(CANARY.encode()).digest())
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
        first.summary_choice.current(1)
        first.set_summary_depth()
        first.show_inspection(inspect_project(project))
        first.entry.insert(0, CANARY)
        first.send()
        assert CANARY in first.transcript.get("1.0", "end")
        workspace.new()
        second = workspace.current
        bind_project(second, project)
        second.summary_choice.current(0)
        second.set_summary_depth()
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
        assert workspace.current.summary_choice.get() == "Aperçu"
        workspace.show(first)
        assert workspace.current.project == root / "project"
        assert workspace.current.summary_choice.get() == "Détaillé"
        assert "script Python" in workspace.current.session_observation.cget("text")
        assert CANARY not in workspace.current.transcript.get("1.0", "end")
        workspace.show(second)
        assert workspace.current.project == root / "project"
        assert workspace.current.summary_choice.get() == "Aperçu"
        assert "aucun test repéré" in workspace.current.session_observation.cget("text")
    finally:
        window.destroy()
    verify_storage(root)


def measure(root, baseline_ms, samples):
    window = tk.Tk()
    window.withdraw()
    tasks = NotesTasks(root / "runs", None, None, False)
    results = []
    try:
        for index in range(samples + 1):
            frame = ttk.Frame(window)
            before = perf_counter()
            workspace = ConversationWorkspace(frame, None, None, None, None, tasks,
                                              project=None, review_prepared=None)
            assert len(workspace.current.session_record.facts) == 2
            window.update_idletasks()
            elapsed = (perf_counter() - before) * 1000
            frame.destroy()
            if index:
                results.append(elapsed)
    finally:
        window.destroy()
    threshold = min(2 * baseline_ms, 500)
    return {"baseline_ms": baseline_ms, "threshold_ms": threshold, "samples": samples, "remembered_facts": 2,
            "median_ms": round(median(results), 3), "passed": median(results) <= threshold}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--baseline-ms", type=float)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--stage", choices=("create", "reopen"))
    cli.add_argument("--workspace", type=Path)
    args = cli.parse_args()
    if args.stage:
        check = create_sessions if args.stage == "create" else reopen_sessions
        check(args.workspace.resolve(strict=True))
        return
    if args.baseline_ms is None or args.baseline_ms <= 0 or args.output is None:
        cli.error("--baseline-ms et --output sont requis")
    with TemporaryDirectory(prefix="akasha-conversation-session-") as directory:
        workspace = Path(directory).resolve()
        for stage in ("create", "reopen"):
            subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "bench.run_conversation_sessions", "--stage", stage,
                            "--workspace", str(workspace)], check=True)
        timing = measure(workspace, args.baseline_ms, samples=20)
        verify_storage(workspace)
    result = {"status": "passed" if timing["passed"] else "failed", "two_sessions_same_project": True,
              "process_restart_verified": True, "structured_facts_restored": True, "synthetic_secret_absent": True,
              "timing": timing}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return int(not timing["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
