"""Rejeu bout en bout du bureau et d’un client MCP sur le pilote CUDA résident."""

import argparse
import asyncio
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time
import tkinter as tk

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from akasha_brain.desktop_conversation import ConversationPane
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.whisper_pilot import cache_path, display
from akasha_brain import whisper_resident
from bench.run_g7_pilot import ROOT


def verify(project, runs):
    sample = "prise-2.wav"
    for name in (sample, "prise-3.flac", "prise-7.wav"):
        shutil.copyfile(ROOT/name, project/name)

    window = tk.Tk()
    window.withdraw()
    timings = []
    try:
        pane = ConversationPane(window, None, None, None, None, NotesTasks(runs, None, None, False),
                                project=project, review_prepared=None)
        for label in ("Transcription · GPU\n", "Transcription · GPU à chaud\n"):
            start = time.perf_counter()
            pane.entry.insert(0, "Transcris "+sample)
            pane.send()
            while pane.intent_job and time.perf_counter()-start < 300:
                window.update()
                time.sleep(.025)
            text = pane.transcript.get("1.0", "end")
            assert label in text and "À vérifier" in text, text[-500:]
            ticket = whisper_resident.read_ticket()
            timings.append(dict(seconds=time.perf_counter()-start, sandbox=ticket["sandbox"], pid=ticket["pid"]))
            print(label.strip(), timings[-1], flush=True)
        assert timings[0]["sandbox"] == timings[1]["sandbox"] and timings[0]["pid"] == timings[1]["pid"]
        assert timings[1]["seconds"] < timings[0]["seconds"]
    finally:
        window.destroy()

    async def mcp(cpu=False):
        env = {"AKASHA_WHISPER_CACHE": str(cache_path()), "AKASHA_WHISPER_GPU_CACHE": str(whisper_resident.cache_path())}
        if cpu:
            env["AKASHA_VRAM_LIMIT_MIB"] = "0"
        params = StdioServerParameters(command=sys.executable, args=["-m", "akasha_brain.mcp_server",
                                       "--project", str(project), "--runs", str(runs)], env=env)
        results = []
        async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
            await client.initialize()
            assert "audio_transcribe" in {t.name for t in (await client.list_tools()).tools}
            for file in ([sample] if cpu else [sample, "prise-3.flac", "prise-7.wav"]):
                start = time.perf_counter()
                out = (await client.call_tool("audio_transcribe", {"file": file})).structured_content
                results.append(dict(file=file, seconds=time.perf_counter()-start, **out))
                print("MCP", file, out["execution"], round(results[-1]["seconds"], 3), flush=True)
                if file == "prise-7.wav":
                    assert out["status"] == "silence" and not out["text"]
                elif cpu:
                    assert out["execution"]["device"] == "cpu" and out["execution"]["fallback_reason"] == "vram_budget"
                else:
                    assert out["execution"] == {"device":"cuda", "reused":True, "residency_id":timings[0]["sandbox"]}, out["execution"]
                    if file == sample:
                        assert display(out) in text, (display(out), text[-1100:])
            denied = await client.call_tool("audio_transcribe", {"file": "../outside.wav"})
            assert denied.is_error
        return results

    results = asyncio.run(mcp())
    fallback = asyncio.run(mcp(cpu=True))
    assert whisper_resident.read_ticket() is None
    return dict(desktop=timings, mcp=results, cpu_fallback=fallback, released=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as tmp:
        project = Path(tmp)/"project"
        project.mkdir()
        result = verify(project, Path(tmp)/"runs")
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", "utf-8")
