"""Rejeu Windows G10. Deux accords réels pour la même page HTTPS statique."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import tkinter as tk
from tkinter import ttk

from akasha_brain.desktop import Desktop
from akasha_brain.desktop_tasks import NotesTasks


PAGE = "https://example.com/"
FOLLOWUP = "Que dit cette page ?"


def button(parent, label):
    for widget in parent.winfo_children():
        if isinstance(widget, ttk.Button) and widget.cget("text") == label:
            return widget
    raise AssertionError(f"Bouton introuvable : {label}")


def send(pane, message):
    pane.entry.insert(0, message)
    button(pane.entry.master, "Envoyer").invoke()
    pane.parent.update()


def decisions(path):
    if not path.exists():
        return []
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT request_id, outcome FROM web_audit ORDER BY seq").fetchall()
    finally:
        db.close()


def replay(root, folder, launches):
    tasks = NotesTasks(folder / "runs", None, None, False)
    sessions = Desktop(root, tasks).conversation
    root.update()
    pane = sessions.current
    assert pane.project is None and pane.entry.winfo_viewable()
    audit = folder / "AkashaBrain" / "web-audit.sqlite"
    turns = []
    expected = []
    for number, request in enumerate((f"Que dit {PAGE} ?", FOLLOWUP), 1):
        send(pane, request)
        prompt = pane.transcript.get("1.0", "end").rsplit("Accord requis\n", 1)[-1]
        assert prompt.splitlines()[1] == PAGE
        assert pane.confirm.winfo_viewable() and pane.confirm.cget("text") == "Autoriser la lecture"
        assert decisions(audit) == expected and len(launches) == number - 1
        start = monotonic()
        pane.confirm.invoke()
        while pane.intent_job is not None and monotonic() - start < 20:
            root.update()
            sleep(0.01)
        elapsed = monotonic() - start
        transcript = pane.transcript.get("1.0", "end")
        assert transcript.count("Texte public relevé\n") == number, transcript.rsplit("\n\n", 2)[-2]
        lines = transcript.rsplit("Texte public relevé\n", 1)[1].strip().splitlines()
        assert lines[0] == PAGE and re.fullmatch(r"Relevé le \d{2}/\d{2}/\d{4} à \d{2}:\d{2}", lines[1])
        assert "Example Domain" in "\n".join(lines[3:])
        rows = decisions(audit)
        request_id = rows[-1][0]
        assert request_id not in {key for key, _ in expected}
        expected.extend([(request_id, "authorized"), (request_id, "collected")])
        assert rows == expected and len(launches) == number
        turns.append({"turn": number, "request_id": request_id, "displayed_date": lines[1],
                      "page_heading": "Example Domain", "click_to_display_s": round(elapsed, 3)})

    button(sessions.selector.master, "Nouvelle session").invoke()
    other = sessions.current
    send(other, FOLLOWUP)
    assert other.session_record.id != pane.session_record.id and other.project is None
    isolated = other.transcript.get("1.0", "end")
    assert PAGE not in isolated and "Accord requis" not in isolated
    assert "Collez une URL HTTPS" in isolated
    send(other, f"Quel lien consulter, {PAGE} ou {PAGE}guide ?")
    assert "Indiquez une seule URL" in other.transcript.get("1.0", "end")
    assert not other.confirm.winfo_viewable()
    send(other, PAGE)
    assert other.confirm.winfo_viewable()
    send(other, "Annuler")
    assert not other.confirm.winfo_viewable()
    assert decisions(audit) == expected and len(launches) == 2
    return {"platform": platform.platform(), "python": platform.python_version(), "tk": tk.TkVersion,
            "finished_utc": datetime.now(timezone.utc).isoformat(), "page": PAGE, "turns": turns,
            "host_reader_launches": len(launches), "audit_outcomes": [outcome for _, outcome in expected],
            "new_session_isolated": True, "ambiguous_urls_prompted": True, "cancel_before_read": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Enregistrer le résultat JSON du rejeu réussi.")
    args = parser.parse_args()
    launches = []

    def observe(event, args):
        if event == "subprocess.Popen" and "akasha_brain.web_collection" in args[1]:
            launches.append(monotonic())

    sys.addaudithook(observe)
    with TemporaryDirectory(prefix="akasha-g10-") as directory:
        os.environ["LOCALAPPDATA"] = directory
        root = tk.Tk()
        try:
            report = replay(root, Path(directory), launches)
        finally:
            root.destroy()
    result = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
