"""Agrège les trois démarrages par mode et vérifie les horodatages des blocs."""

from hashlib import sha256
import json
from pathlib import Path
from statistics import median

from bench.g8_qwen_streaming import OUT
from bench.g8_qwen_listening import CORPUS, MODEL, REVISION, verify_model


def main():
    sessions = [json.loads((OUT/f"{mode}-{i}.json").read_bytes())
                for i in (1, 2, 3) for mode in ("stream", "full")]
    assert len({session["process"] for session in sessions}) == 6
    timings = {}
    for session in sessions:
        assert session["weights_revision"] == REVISION
        assert session["corpus_sha256"] == sha256(CORPUS.read_bytes()).hexdigest()
        assert [r["phrase"] for r in session["runs"][:4]] == [1, 1, 2, 3]
        for r in session["runs"]:
            blocks = r["blocks"]
            assert sum(b["frames"] for b in blocks) == r["frames"]
            assert all(earlier["ready_s"] <= later["ready_s"] for earlier, later in zip(blocks, blocks[1:]))
            if session["mode"] == "stream":
                assert len(blocks) > 1 and r["first_sound_s"] < blocks[-1]["ready_s"]
            else:
                assert len(blocks) == 1
            if r["style"] == "reference":
                condition = "cold" if r["cold"] else "warm"
                timings.setdefault(f"{session['mode']}_{condition}_phrase{r['phrase']}", []).append(r["first_sound_s"])
    for style in ("reference", "nuance", "sobre"):
        for n in range(1, 4):
            take = next(r for r in sessions[0]["runs"] if r["style"] == style and r["phrase"] == n)
            assert sha256((OUT/style/f"{n}.wav").read_bytes()).hexdigest() == take["wav_sha256"]
    assert MODEL.exists() and verify_model()
    report = {
        "definition": "Seconds until playable non-silent host PCM at native 24 kHz, 10 ms windows at -50 dBFS RMS. "
                      "Accounts for digital leading silence and chunk arrival. Speaker hardware excluded.",
        "cold": "Fresh process, includes Python runtime library imports, model load, CUDA setup and graph capture. "
                "OS file cache uncontrolled. No downloads.",
        "warm": "Subsequent call with the same resident CUDA model and graphs, seed reset each request.",
        "process_order": ["stream-1", "full-1", "full-2", "stream-2", "stream-3", "full-3"],
        "summary": {label: {"n": len(vals), "median_s": median(vals), "min_s": min(vals), "max_s": max(vals)}
                    for label, vals in timings.items()},
        "sessions": sessions,
    }
    output = Path(__file__).resolve().parent / "results/g8-qwen-streaming-v1.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
