"""Vérifie les citations du compte rendu contre les interventions datées avant transcription."""

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import wave

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from akasha_brain import meeting_minutes, whisper_pilot, whisper_resident
from akasha_brain.desktop_conversation import ConversationPane
from akasha_brain.desktop_tasks import NotesTasks

CORPUS = Path(__file__).parent/"corpora/g7-reunion-fr-v1"
FILE = "reunion.wav"
REQUEST = "Résume la réunion reunion.wav"


def desktop(project, runs):
    window = tk.Tk()
    window.withdraw()
    try:
        pane = ConversationPane(window, None, None, None, None, NotesTasks(runs, None, None, False),
                                project=project, review_prepared=None)
        pane.entry.insert(0, REQUEST)
        pane.send()
        deadline = time.monotonic()+360
        while pane.intent_job and time.monotonic() < deadline:
            window.update()
            time.sleep(.04)
        content = pane.transcript.get("1.0", "end")
        print(content, flush=True)
        assert not pane.intent_job and "Compte rendu\n" in content, content
        return content.split("Compte rendu\n", 1)[1].strip()
    finally:
        window.destroy()


async def mcp(project, runs):
    env = {"AKASHA_WHISPER_CACHE": str(whisper_pilot.cache_path()),
           "AKASHA_WHISPER_GPU_CACHE": str(whisper_resident.cache_path() or "")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "akasha_brain.mcp_server",
                                  "--project", str(project), "--runs", str(runs)], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
        await client.initialize()
        result = await client.call_tool("audio_meeting_minutes", {"file": FILE})
        assert not result.is_error, result.content
        return result.structured_content


def verify(report, reference):
    segments = report["segments"]
    for point in report["summary"] + report["decisions"] + report["actions"]:
        source = point["source"]
        cited = [segments[i] for i in source["segment_indices"]]
        assert source["file"] == FILE and point["text"] in " ".join(s["text"] for s in cited)
        assert (source["start_ms"], source["end_ms"]) == (cited[0]["start_ms"], cited[-1]["end_ms"])
        assert point["transcript_uncertain"] == any(s["uncertain"] for s in cited)
    decision, = report["decisions"]
    assigned, anonymous = report["actions"]
    # Les fenêtres de parole proviennent du WAV et des prises de synthèse, indépendamment de Whisper.
    with wave.open(str(CORPUS/FILE), "rb") as stream:
        pcm = memoryview(stream.readframes(stream.getnframes())).cast("h")
    bounds = {}
    for turn in reference["turns"]:
        active = [ms for ms in range(turn["start_ms"], turn["end_ms"], 10)
                  if sum(s*s for s in pcm[ms*16:(ms+10)*16]) > 160*100**2]
        bounds[turn["role"]] = (active[0], active[-1]+10)
    checks = []
    for point, role, words in (
        (report["summary"][0], "topic", ["portes ouvertes", "bibliothèque"]),
        (decision, "decision", ["grande salle", "lundi matin"]),
        (assigned, "named_action", ["invitations", "jeudi"]),
        (anonymous, "unidentified_action", ["badges", "visiteurs"]),
    ):
        assert all(word in point["text"].casefold() for word in words), point
        source = point["source"]
        begin, end = source["start_ms"], source["end_ms"]
        first, last = bounds[role]
        assert begin <= first and last <= end, (point, bounds[role])
        assert all(other == role or stop <= begin or start >= end for other, (start, stop) in bounds.items())
        checks.append({"role": role, "speech_ms": [first, last], "citation_ms": [begin, end]})
    assert decision in report["summary"] and anonymous in report["summary"]
    assert "vendredi" not in decision["text"].casefold()
    assert assigned["attribution"]["mentioned_owner"] == (None if assigned["transcript_uncertain"] else "Marie")
    assert anonymous["attribution"] == {"mentioned_owner": None, "status": "needs_review"}
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    reference = json.loads((CORPUS/"reference.json").read_bytes())
    assert sha256((CORPUS/FILE).read_bytes()).hexdigest() == reference["sha256"]
    with TemporaryDirectory() as folder:
        root = Path(folder)
        project = root/"project"
        project.mkdir()
        shutil.copyfile(CORPUS/FILE, project/FILE)
        shown = desktop(project, root/"runs")
        report = asyncio.run(mcp(project, root/"runs"))
    assert shown == meeting_minutes.display(report)
    checks = verify(report, reference)
    args.report.write_text(json.dumps({"input_sha256": reference["sha256"], "request": REQUEST,
        "desktop": shown, "mcp": report, "verified_against_reference": True, "citation_checks": checks},
        ensure_ascii=False, indent=2)+"\n", "utf-8")
