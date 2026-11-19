"""Rejeu des boutons de lecture et d’arrêt du bureau sur la sortie audio Windows."""

import ctypes
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tkinter as tk
from unittest.mock import patch

from akasha_brain import piper_voice
from akasha_brain.desktop_conversation import ConversationPane
from akasha_brain.desktop_tasks import NotesTasks
from bench.run_guided_repair import BENCH


def opened_devices():
    output = ctypes.create_unicode_buffer(64)
    code = ctypes.windll.winmm.mciSendStringW("sysinfo waveaudio quantity open", output, len(output), None)
    if code:
        raise RuntimeError(f"Impossible de compter les périphériques MCI ({code}).")
    return int(output.value)


def wait(window, predicate, timeout):
    end = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() > end:
            raise TimeoutError("Le bureau n’a pas atteint l’état attendu.")
        window.update()
        time.sleep(.015)


def run():
    phrase = json.loads((BENCH/"corpora/g8-siwis-fr-v1/phrases.json").read_bytes())[0]["text"]
    observations = {}
    native_play = piper_voice.play_wav

    def observed_play(data, checkpoint, on_start):
        # MCI associe les périphériques au thread qui les a ouverts.
        observations["before"] = opened_devices()
        def started():
            observations["playing"] = opened_devices()
            on_start()
        try:
            native_play(data, checkpoint, started)
        finally:
            observations["after"] = opened_devices()

    with TemporaryDirectory() as tmp:
        tasks = NotesTasks(Path(tmp)/"runs", None, None, False)
        window = tk.Tk()
        window.withdraw()
        try:
            pane = ConversationPane(window, None, None, None, None, tasks, project=None, review_prepared=None)
            pane.add("Akasha", phrase)
            reader = pane.reader
            with patch.dict(os.environ, {"AKASHA_QWEN_HOME": str(Path(tmp)/"gpu-absent")}), \
                    patch.object(piper_voice, "play_wav", observed_play):
                start = time.perf_counter()
                reader.read_button.invoke()
                wait(window, lambda: "Piper · CPU" in reader.status.cget("text") or reader.worker is None, 180)
                assert reader.worker is not None, reader.status.cget("text")
                latency = time.perf_counter()-start
                assert observations["playing"] > observations["before"], observations
                assert tasks.scheduler.submit(lambda: "disponible").result(timeout=1) == "disponible"
                start = time.perf_counter()
                reader.stop_button.invoke()
                wait(window, lambda: reader.worker is None, 3)
                stopped = time.perf_counter()-start
            assert reader.status.cget("text") == "Lecture arrêtée."
            assert observations["after"] == observations["before"]
            return {"displayed_reply": phrase, "seconds_to_playing": latency, "seconds_to_stopped": stopped,
                    "open_devices_on_audio_thread": observations, "windows_output_released": True,
                    "interactive_queue_available_during_playback": True}
        finally:
            window.destroy()


if __name__ == "__main__":
    result = run()
    print(result, flush=True)
    (BENCH/"results/g8-desktop-v1.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", "utf-8")
