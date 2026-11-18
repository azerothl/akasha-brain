"""Fige puis rejoue un deuxième lot FLEURS via la conversation et le serveur MCP."""

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import wave

import numpy as np

from akasha_brain.conversation_planning import execute_intents, infer_intent, load_conversation_catalog, references
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.mcp_server import create_server
from akasha_brain.whisper_pilot import display
from bench.freeze_g7_french import pcm, REV
from bench.run_g7_asr import words, errors

ROOT = Path(__file__).parent / "corpora" / "g7-fr-pilot-v2"
SELECTION = [
    ("3683527580499257367", None, ["TogiNet Radio"], "wav"),
    ("15679345674072383870", 8, ["Rossby"], "wav"),
    ("2757290274126351777", None, ["Haïti"], "flac"),
    ("5472816019113202964", None, ["Ottawa", "Canada"], "wav"),
    ("3172268488349984843", 5, ["Bali"], "wav"),
    ("10166091086920486572", 10, ["Mashhad"], "wav"),
]


def freeze(cache):
    rows = {r[1]: r for r in (l.split("\t") for l in (cache/"test.tsv").read_text("utf-8").splitlines())}
    wanted = {key+".wav" for key, *_ in SELECTION}
    with tarfile.open(cache/"test.tar.gz", "r|gz") as archive:
        inputs = {Path(m.name).name: archive.extractfile(m).read() for m in archive
                  if m.isfile() and Path(m.name).name in wanted}
    ROOT.mkdir(exist_ok=True)
    old = json.loads((ROOT.parent/"g7-fr-v1"/"manifest.json").read_bytes())["clips"]
    clips = []
    for index, (key, snr, names, fmt) in enumerate([*SELECTION, ("silence", None, [], "wav")]):
        if key == "silence":
            samples = np.zeros(68000)
            reference, sentence = "", None
        else:
            sentence, _, reference, *_ = rows[key+".wav"]
            assert sentence not in {c.get("sentence_id") for c in old}
            samples = pcm(inputs[key+".wav"])
            if snr is not None:
                noise = np.random.default_rng(int(key)).standard_normal(len(samples))
                samples += noise*np.linalg.norm(samples)/(np.linalg.norm(noise)*10**(snr/20))
        path = ROOT/f"prise-{index+1}.{fmt}"
        with TemporaryDirectory() as tmp:
            wav = path if fmt == "wav" else Path(tmp)/"audio.wav"
            with wave.open(str(wav), "wb") as out:
                out.setparams((1, 2, 16000, 0, "NONE", ""))
                out.writeframes(np.clip(np.rint(samples*32768), -32768, 32767).astype("<i2").tobytes())
            if fmt == "flac":
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-map_metadata", "-1", path], check=True)
        clips.append({"file": path.name, "source_id": key, "sentence_id": sentence, "snr_db": snr, "names": names,
                      "reference": reference, "frames": len(samples), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"source": f"https://huggingface.co/datasets/google/fleurs/tree/{REV}/data/fr_fr",
                "license": "FLEURS, Conneau et al., Google, CC BY 4.0. Conversion PCM16 / FLAC, bruit et silence.",
                "uncertainty_rule": "lexical token p < 0.50 or segment mean < 0.80; missing scores or clipped time",
                "clips": clips}
    (ROOT/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", "utf-8")


def conversation(project, name):
    request = "Transcris "+name
    catalog = load_conversation_catalog()
    refs = references(request)
    intent = infer_intent(None, "", request, refs, catalog, selected=True)
    result, = execute_intents(request, intent, refs, project, catalog)
    if not hasattr(result, "output"):
        raise RuntimeError(result)
    assert result.plan.capability == "audio.transcribe"
    assert ("À vérifier" in display(result.output)) == any(s["uncertain"] for s in result.output["segments"])
    return result.output


def error_locations(reference, segments):
    """Distance de mots avec attribution des suppressions au mot suivant (ou au dernier)."""
    ref = words(reference)
    hyp = [(w, i) for i, s in enumerate(segments) for w in words(s["text"])]
    table = [list(range(len(hyp)+1))]
    for i, word in enumerate(ref, 1):
        row = [i]
        for j, (other, _) in enumerate(hyp, 1):
            row.append(min(row[-1]+1, table[-1][j]+1, table[-1][j-1]+(word != other)))
        table.append(row)
    counts = [0]*len(segments)
    i, j = len(ref), len(hyp)
    while hyp and (i or j):
        if i and j and table[i][j] == table[i-1][j-1]+(ref[i-1] != hyp[j-1][0]):
            counts[hyp[j-1][1]] += ref[i-1] != hyp[j-1][0]
            i, j = i-1, j-1
        elif i and table[i][j] == table[i-1][j]+1:
            counts[hyp[min(j, len(hyp)-1)][1]] += 1
            i -= 1
        else:
            counts[hyp[j-1][1]] += 1
            j -= 1
    return counts


def audit(report):
    refs = {c["file"]: c["reference"] for c in json.loads((ROOT/"manifest.json").read_bytes())["clips"]}
    counts = Counter()
    for row in report["results"]:
        attributed = error_locations(refs[row["file"]], row["segments"])
        row["word_errors_by_segment"] = attributed
        if row["segments"]:
            assert sum(attributed) == row["errors"]
        for n, seg in zip(attributed, row["segments"], strict=True):
            counts[("flagged" if seg["uncertain"] else "unflagged") + ("_with_error" if n else "_exact")] += 1
    report["segment_audit"] = dict(counts)
    return report


async def replay():
    manifest = json.loads((ROOT/"manifest.json").read_bytes())
    rows = []
    with TemporaryDirectory() as tmp:
        project = Path(tmp)/"project"
        project.mkdir()
        server = create_server(NotesTasks(Path(tmp)/"runs", None, None, False), project=project)
        assert "audio_transcribe" in {t.name for t in await server.list_tools()}
        for i, clip in enumerate(manifest["clips"]):
            name = clip["file"]
            raw = (ROOT/name).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == clip["sha256"]
            (project/name).write_bytes(raw)
            # Uniquement les enregistrements sont accessibles depuis le projet.
            modes = ("conversation", "MCP") if i in (0, len(manifest["clips"])-1) else (("MCP",) if i%2 else ("conversation",))
            prior = None
            for mode in modes:
                if mode == "conversation":
                    out = conversation(project, name)
                else:
                    out = (await server.call_tool("audio_transcribe", {"file": name})).structured_content
                if prior is not None:
                    # The second surface can legitimately reuse the first surface's GPU worker.
                    assert {k: v for k, v in prior.items() if k != "execution"} == {
                        k: v for k, v in out.items() if k != "execution"}
                prior = out
            segments = out["segments"]
            assert all(0 <= s["start_ms"] < s["end_ms"] <= out["duration_ms"] for s in segments)
            assert out["status"] != "silence" if clip["reference"] else out["status"] == "silence" and not out["text"]
            ref, hyp = words(clip["reference"]), words(out["text"])
            # Une mention absente peut rester confiante. Conserver cette information pour la revue.
            flagged = " "+" ".join(words(" ".join(s["text"] for s in segments if s["uncertain"])))+" "
            names = {n: {"found": " "+" ".join(words(n))+" " in " "+" ".join(hyp)+" ",
                         "in_flagged_text": " "+" ".join(words(n))+" " in flagged} for n in clip["names"]}
            rows.append({"file": name, "surfaces": modes, "errors": errors(ref, hyp), "words": len(ref),
                         "snr_db": clip["snr_db"], "names": names, **out})
            print(name, modes, out["status"], flush=True)
        assert {p.name for p in project.iterdir()} == {c["file"] for c in manifest["clips"]}
    return {"corpus_sha256": hashlib.sha256((ROOT/"manifest.json").read_bytes()).hexdigest(),
            "status_counts": dict(Counter(r["status"] for r in rows)), "results": rows}


def verify_surfaces():
    import shutil
    import sys
    import time
    import tkinter as tk
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from akasha_brain.desktop_conversation import ConversationPane
    from akasha_brain.whisper_pilot import cache_path

    with TemporaryDirectory() as tmp:
        project = Path(tmp)/"project"
        project.mkdir()
        runs = Path(tmp)/"runs"
        clips = ("prise-2.wav", "prise-7.wav")
        for name in clips:
            shutil.copyfile(ROOT/name, project/name)

        async def external_client():
            params = StdioServerParameters(command=sys.executable, args=["-m", "akasha_brain.mcp_server",
                "--project", str(project), "--runs", str(runs)], env={"AKASHA_WHISPER_CACHE": str(cache_path())})
            async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
                await client.initialize()
                assert "audio_transcribe" in {tool.name for tool in (await client.list_tools()).tools}
                outputs = {}
                for name in clips:
                    reply = await client.call_tool("audio_transcribe", {"file": name})
                    outputs[name] = reply.structured_content
                return outputs

        outputs = asyncio.run(external_client())
        assert outputs[clips[0]]["status"] == "needs_review"
        assert outputs[clips[1]]["status"] == "silence"
        window = tk.Tk()
        window.withdraw()
        observations = []
        try:
            pane = ConversationPane(window, None, None, None, None, NotesTasks(runs, None, None, False),
                                    project=project, review_prepared=None)
            for name in clips:
                pane.entry.insert(0, "Transcris "+name)
                pane.send()
                deadline = time.monotonic()+180
                while pane.intent_job and time.monotonic() < deadline:
                    window.update()
                    time.sleep(0.05)
                expected = display(outputs[name])
                assert not pane.intent_job and expected in pane.transcript.get("1.0", "end"), name
                observations.append({"file": name, "conversation": expected, "mcp": outputs[name]})
        finally:
            window.destroy()
        return {"transport": "stdio", "interface": "ConversationPane", "observations": observations}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("stage", choices=("freeze", "replay", "surfaces"))
    cli.add_argument("path", type=Path, help="Cache FLEURS pour freeze, rapport JSON pour replay")
    args = cli.parse_args()
    if args.stage == "freeze":
        freeze(args.path)
    else:
        result = verify_surfaces() if args.stage == "surfaces" else audit(asyncio.run(replay()))
        args.path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", "utf-8")
