"""Rejoue deux installations vides sur Windows, avec les sources HTTPS du catalogue."""

import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time
import tkinter as tk
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import ElicitResult

from akasha_brain.desktop_conversation import ConversationPane
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.image_assets import WHISPER_ENGINE, WHISPER_MODEL
from akasha_brain.whisper_pilot import display
from bench.run_g7_pilot import ROOT

SAMPLE = "prise-2.wav"
ARTIFACTS = (WHISPER_ENGINE, WHISPER_MODEL)


def identify(message):
    item, = [a for a in ARTIFACTS if a.sha256 in message and a.url in message]
    return item.filename


def cache_state(cache):
    assert not list(cache.glob("*.partial"))
    return {"verified_downloads": len(list(cache.glob("approvals/*/receipt.json"))),
            "qualified": (cache/"qualification-whisper-small.json").is_file()}


def model_in_flight(cache, prompts):
    return (prompts == [a.filename for a in ARTIFACTS]
            and any(p.stat().st_size > 0 for p in cache.glob("*.partial")))


async def mcp_run(project, cache, file, decisions, *, interrupt=False):
    prompts = []

    async def answer(_, params):
        prompts.append(identify(params.message))
        action = decisions[len(prompts)-1]
        print("MCP", prompts[-1], action, flush=True)
        return ElicitResult(action=action, content={"autoriser": True} if action == "accept" else None)

    env = {"AKASHA_WHISPER_CACHE": str(cache), "AKASHA_WHISPER_GPU_CACHE": ""}
    params = StdioServerParameters(command=sys.executable, args=["-m", "akasha_brain.mcp_server", "--project",
                                  str(project), "--runs", str(cache.parent/"runs")], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w, elicitation_callback=answer) as client:
        await client.initialize()
        call = asyncio.create_task(client.call_tool("audio_transcribe", {"file": file}))
        if interrupt:
            async with asyncio.timeout(90):
                while not model_in_flight(cache, prompts):
                    assert not call.done(), call.result() if call.done() else None
                    await asyncio.sleep(.015)
                call.cancel()
                with suppress(asyncio.CancelledError):
                    await call
                while list(cache.glob("*.partial")):
                    await asyncio.sleep(.025)
                assert not (cache/WHISPER_MODEL.filename).exists()
            return prompts, None
        result = await call
    assert len(prompts) == len(decisions), (prompts, result.content)
    return prompts, result


def mcp_trial(project, cache):
    actions = {}
    interrupted = cache.with_name("mcp-interrupted")
    prompts, _ = asyncio.run(mcp_run(project, interrupted, SAMPLE, ["accept", "accept"], interrupt=True))
    state = cache_state(interrupted)
    assert state == {"verified_downloads": 1, "qualified": False}
    actions["cancel_during_model_transfer"] = {"prompts": prompts, **state}
    for case, file, decisions, error in (
        ("outside", "../other/"+SAMPLE, [], "interdit"),
        ("declined", SAMPLE, ["decline"], "refusé"),
        ("cancelled", SAMPLE, ["cancel"], "annulée"),
        ("cold", SAMPLE, ["accept", "accept"], None),
        ("restarted", SAMPLE, [], None),
    ):
        prompts, result = asyncio.run(mcp_run(project, cache, file, decisions))
        state = cache_state(cache)
        if error:
            assert result.is_error and error in str(result.content), result
            assert state == {"verified_downloads": 0, "qualified": False}
        else:
            out = result.structured_content
            assert not result.is_error and out["segments"] and out["execution"]["device"] == "cpu", result
            assert state == {"verified_downloads": 2, "qualified": True}
            if case == "cold":
                assert prompts == [a.filename for a in ARTIFACTS]
                transcript = out["text"]
                formatted = display(out)
                receipt_time = (cache/"qualification-whisper-small.json").stat().st_mtime_ns
            else:
                assert transcript == out["text"]
                assert (cache/"qualification-whisper-small.json").stat().st_mtime_ns == receipt_time
        actions[case] = {"prompts": prompts, **state}
    return actions, formatted


def desktop_trial(project, cache, transcript):
    outcomes = {}
    with patch.dict(os.environ, AKASHA_WHISPER_CACHE=str(cache), AKASHA_WHISPER_GPU_CACHE=""):
        for case, file, decisions in (
            ("outside", "../other/"+SAMPLE, []), ("declined", SAMPLE, ["decline"]),
            ("cancelled", SAMPLE, ["cancel"]), ("switch_project", SAMPLE, ["switch"]),
            ("cancel_during_model_transfer", SAMPLE, ["accept", "accept"]), ("cold", SAMPLE, ["accept", "accept"]),
            ("restarted", SAMPLE, []),
        ):
            prompts = []
            active = cache.with_name("desktop-interrupted") if case == "cancel_during_model_transfer" else cache
            os.environ["AKASHA_WHISPER_CACHE"] = str(active)
            window = tk.Tk()
            window.withdraw()
            try:
                pane = ConversationPane(window, None, None, None, None, NotesTasks(cache.parent/"runs", None, None, False),
                                        project=project, review_prepared=None)
                pane.entry.insert(0, "Transcris "+file)
                pane.send()
                job = pane.intent_job[3]
                deadline = time.monotonic()+900
                while pane.intent_job:
                    assert time.monotonic() < deadline, case
                    window.update()
                    if pane.audio_decision is not None:
                        msg = pane.transcript.get("1.0", "end").rsplit("Autoriser le téléchargement de ", 1)[-1]
                        prompts.append(identify(msg))
                        choice = decisions[len(prompts)-1]
                        print("Bureau", prompts[-1], choice, flush=True)
                        if choice == "accept":
                            pane.confirm.invoke()
                        elif choice == "decline":
                            pane.refuse_audio.invoke()
                        elif choice == "switch":
                            pane.select_project(project.parent/"other")
                        else:
                            pane.entry.insert(0, "Annuler")
                            pane.send()
                    if case == "cancel_during_model_transfer" and model_in_flight(active, prompts):
                        pane.entry.insert(0, "Annuler")
                        pane.send()
                    time.sleep(.04)
                text = pane.transcript.get("1.0", "end")
                job.result(timeout=45)
                state = cache_state(active)
                if case in ("cold", "restarted"):
                    assert "Transcription · CPU" in text and transcript in text, text
                    assert state == {"verified_downloads": 2, "qualified": True}
                    receipt = (active/"qualification-whisper-small.json").stat().st_mtime_ns
                    if case == "cold":
                        cold_receipt = receipt
                    else:
                        assert receipt == cold_receipt
                elif case == "cancel_during_model_transfer":
                    assert state == {"verified_downloads": 1, "qualified": False}
                    assert not (active/WHISPER_MODEL.filename).exists() and "Transcription · CPU" not in text
                else:
                    assert "Transcription · CPU" not in text and state == {"verified_downloads": 0, "qualified": False}
                    if case not in ("cancelled", "switch_project"):
                        assert pane.intent_error is not None, text
                assert len(prompts) == len(decisions)
                outcomes[case] = {"prompts": prompts, **state}
            finally:
                window.destroy()
    return outcomes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        project = root/"project"
        for directory in (project, root/"other"):
            directory.mkdir()
            shutil.copyfile(ROOT/SAMPLE, directory/SAMPLE)
        mcp, transcript = mcp_trial(project, root/"mcp-cache")
        desktop = desktop_trial(project, root/"desktop-cache", transcript)
        result = {"engine": "whisper.cpp-small", "qualification_device": "cpu", "source": "HTTPS",
                  "decisions": "automated", "input": SAMPLE, "text": transcript, "desktop": desktop, "mcp": mcp}
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", "utf-8")
