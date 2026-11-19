"""Run with python -m bench.verify_g8_vivian_desktop on the integrated Windows desktop."""

from bisect import bisect_right
from contextlib import ExitStack
import ctypes
from io import BytesIO
import json
import os
from pathlib import Path
from statistics import median
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
import tkinter as tk
from unittest.mock import patch
from uuid import uuid4
import wave

from akasha_brain import piper_voice, stream_audio
from akasha_brain.desktop_tasks import NotesTasks
from bench.run_guided_repair import BENCH


REPORT = BENCH / "results/g8-vivian-desktop-v1.json"
STOP_TIMEOUT = 3  # Same UI deadline as verify_g8_desktop.


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Onset:
    """First 10 ms window at -50 dBFS RMS in continuous little-endian mono16."""

    def __init__(self, rate):
        self.width = rate // 100
        self.offset = 0
        self.tail = b""
        self.frame = None

    def feed(self, pcm):
        if self.frame is not None:
            return
        data = self.tail + pcm
        step = self.width * 2
        limit = len(data) // step * step
        for start in range(0, limit, step):
            samples = memoryview(data)[start:start + step].cast("h")
            if sum(v * v for v in samples) >= self.width * 32768**2 * 1e-5:
                self.frame = self.offset
                return
            self.offset += self.width
        self.tail = data[limit:]


class WaveTrace:
    """One read-button invocation. Observe successful native submissions including partial writes."""

    def __init__(self, row):
        self.row = row
        self.onset = Onset(stream_audio.SAMPLE_RATE)
        self.ends = []
        self.writes = []
        self.outputs = []
        self.started = None
        self.stop = None

    def observe(self, stack):
        native_output = stream_audio.PCMOutput
        load = stream_audio._load_winmm

        def output(*args, **kwargs):
            device = native_output(*args, **kwargs)
            self.outputs.append(device)
            return device

        def load_observed():
            api = load()
            write, reset, close = api.waveOutWrite, api.waveOutReset, api.waveOutClose

            def submit(handle, pointer, size):
                header = ctypes.cast(pointer, ctypes.POINTER(stream_audio._WaveHeader)).contents
                pcm = ctypes.string_at(header.data, header.length)
                before = perf_counter()
                result = write(handle, pointer, size)
                if not result:
                    self.onset.feed(pcm)
                    self.writes.append(before)
                    self.ends.append((self.ends[-1] if self.ends else 0) + len(pcm) // 2)
                return result

            def discard(handle):
                # close() already holds the position lock. Read via the native API.
                pos = stream_audio._MMTime(stream_audio.TIME_SAMPLES)
                if self.stop is not None and not api.waveOutGetPosition(handle, ctypes.byref(pos), ctypes.sizeof(pos)):
                    frames = {stream_audio.TIME_SAMPLES: pos.value, stream_audio.TIME_BYTES: pos.value // 2,
                              stream_audio.TIME_MS: pos.value * stream_audio.SAMPLE_RATE // 1000}.get(pos.unit)
                    if frames is not None and self.ends:
                        self.row["unplayed_frames_at_reset"] = self.ends[-1] - frames
                return reset(handle)

            def release(handle):
                result = close(handle)
                if not result:
                    self.row["device_closed_s"] = perf_counter() - self.started
                return result

            api.waveOutWrite, api.waveOutReset, api.waveOutClose = submit, discard, release
            return api

        stack.enter_context(patch.object(stream_audio, "PCMOutput", output))
        stack.enter_context(patch.object(stream_audio, "_load_winmm", load_observed))

    def sample(self):
        if not self.ends or self.outputs[-1].closed:
            return 0, 0
        device = self.outputs[-1]
        try:
            cursor = device.position_frames()
        except RuntimeError:
            if device.closed:
                return 0, 0
            raise
        now = perf_counter() - self.started
        if self.onset.frame is not None and cursor > self.onset.frame and "first_sound_s" not in self.row:
            self.row.update(first_sound_s=now, onset_frame=self.onset.frame, device_cursor_frame=cursor)
        return cursor, len(self.ends) - bisect_right(self.ends, cursor)

    def verify_closed(self):
        require(self.outputs and all(output.closed for output in self.outputs), "waveOut still open or never used")
        require("device_closed_s" in self.row, "Missing successful waveOutClose")
        self.row.update(submitted_blocks=len(self.ends), submitted_frames=self.ends[-1], output_closed=True)
        if self.stop is not None:
            self.row["late_writes"] = sum(t >= self.stop for t in self.writes)
            require(self.row["late_writes"] == 0, "waveOutWrite after Stop")


def observe_piper(stack, row):
    synthesize, play = piper_voice.synthesize, piper_voice.play_wav
    wav_bytes = None

    def synthesis(text, *args, **kwargs):
        nonlocal wav_bytes
        wav_bytes, proof = synthesize(text, *args, **kwargs)
        row["piper"] = dict(text=text, **proof)
        return wav_bytes, proof

    def playback(data, checkpoint, on_start):
        require(data == wav_bytes, "MCI received different audio from Piper")
        with wave.open(BytesIO(data)) as wav:
            rate = wav.getframerate()
            onset = Onset(rate)
            onset.feed(wav.readframes(wav.getnframes()))
        require(onset.frame is not None, "Silent Piper WAV")
        alias_id = uuid4()
        alias = "akasha" + alias_id.hex
        def mci(command):
            buf = ctypes.create_unicode_buffer(64)
            code = ctypes.windll.winmm.mciSendStringW(command, buf, len(buf), None)
            require(code == 0, f"MCI {command}: {code}")
            return buf.value

        devices_before = int(mci("sysinfo waveaudio quantity open"))
        active = False

        def started():
            nonlocal active
            active = True
            require(int(mci("sysinfo waveaudio quantity open")) > devices_before, "Piper MCI device did not open")
            mci(f"set {alias} time format milliseconds")
            on_start()

        def check():
            checkpoint()
            if active and "first_sound_s" not in row:
                frame = int(mci(f"status {alias} position")) * rate // 1000
                if frame > onset.frame:
                    row.update(first_sound_s=perf_counter() - row["click_time"], onset_frame=onset.frame,
                               device_cursor_frame=frame, sample_rate=rate)

        with patch.object(piper_voice, "uuid4", return_value=alias_id):
            play(data, check, started)
        row["output_closed"] = int(mci("sysinfo waveaudio quantity open")) == devices_before
        require(active and row["output_closed"], "Piper MCI device did not close")

    stack.enter_context(patch.object(piper_voice, "synthesize", synthesis))
    stack.enter_context(patch.object(piper_voice, "play_wav", playback))


def read(window, pane, voice, row, *, narration=False, stop=False, fallback=False):
    reader = pane.reader
    text = row["text"]
    if narration:
        pane.add("Akasha", text, narration_only=True)
    else:
        pane.add("Akasha", text)
    require(text in pane.transcript.get("1.0", "end"), "Reply missing from the conversation")
    trace = WaveTrace(row)
    stream = voice.stream
    row.update(qwen_calls=[], sample_rate=stream_audio.SAMPLE_RATE)

    def observe_stream(text, style, checkpoint, on_pcm):
        call = dict(text=text, style=style, pcm_blocks=0)
        row["qwen_calls"].append(call)

        def pcm(block):
            call["pcm_blocks"] += 1
            return on_pcm(block)

        return stream(text, style, checkpoint, pcm)

    with ExitStack() as stack:
        trace.observe(stack)
        observe_piper(stack, row)
        stack.enter_context(patch.object(voice, "stream", observe_stream))
        require(reader.read_button.instate(["!disabled"]), "Read button disabled")
        trace.started = row["click_time"] = perf_counter()
        reader.read_button.invoke()
        try:
            while reader.worker is not None:
                window.update()
                status = reader.status.cget("text")
                cursor, queued = trace.sample()
                if "Lecture en cours" in status:
                    row.setdefault("playing_status", status)
                    if stop and trace.stop is None and "first_sound_s" in row and queued >= 2:
                        require(reader.stop_button.instate(["!disabled"]), "Stop button disabled")
                        row.update(cursor_at_stop=cursor, queued_blocks_at_stop=queued)
                        trace.stop = perf_counter()
                        reader.stop_button.invoke()
                if trace.stop is not None and perf_counter() - trace.stop > STOP_TIMEOUT:
                    raise TimeoutError(f"Stop timed out: {status}")
                if perf_counter() - trace.started > 240:
                    raise TimeoutError(f"Read timed out: {status}")
                if reader.worker is not None:
                    sleep(.005)
            idle_at = perf_counter()
        finally:
            if reader.worker is not None:
                reader.stop_button.invoke()
                until = perf_counter() + 5
                while reader.worker is not None and perf_counter() < until:
                    window.update()
                    sleep(.01)
            row.pop("click_time", None)
        row.update(final_status=reader.status.cget("text"), elapsed_s=idle_at - trace.started, pid=voice.pid)
        expected = "Lecture arrêtée." if stop else "Lecture terminée."
        require(row["final_status"] == expected, f'{row["case"]}: {row["final_status"]}')
        require("playing_status" in row and "first_sound_s" in row, "Missing playback status or audible cursor")
        require(reader.read_button.instate(["!disabled"]) and reader.stop_button.instate(["disabled"]),
                "Read/Stop buttons did not return to idle")
        if trace.outputs:
            trace.verify_closed()
        if fallback:
            require(row.get("piper", {}).get("text") == text and row.get("output_closed"), "Missing Piper playback")
            require(not any(c["pcm_blocks"] for c in row["qwen_calls"]), "Qwen supplied fallback audio")
        else:
            require(trace.outputs and "piper" not in row, "Expected Qwen on waveOut")
            calls = row["qwen_calls"]
            require(len(calls) == 1 and calls[0]["text"] == text and calls[0]["style"] == row["expected_style"]
                    and calls[0]["pcm_blocks"] > 0, f"Unexpected Qwen stream: {calls}")
        if stop:
            require(trace.stop is not None and row.get("unplayed_frames_at_reset", 0) > 0,
                    "Stop did not discard queued audio")
            row.update(stop_to_close_s=row["device_closed_s"] - (trace.stop - trace.started),
                       stop_to_idle_s=idle_at - trace.stop)
    return trace


def run(report):
    from akasha_brain.desktop_conversation import ConversationPane
    from akasha_brain.qwen_resident import VOICE

    question, mixed, narration = json.loads((BENCH / "corpora/g8-prosodie-v1/phrases.json").read_bytes())
    with TemporaryDirectory() as tmp:
        tasks = NotesTasks(Path(tmp) / "runs", None, None, False)
        window = tk.Tk()
        try:
            pane = ConversationPane(window, None, None, None, None, tasks, project=None, review_prepared=None)
            window.update()
            VOICE.close()
            require(not VOICE.pid, "Cold run still has a resident")

            def case(name, text, style=None, **options):
                row = dict(case=name, text=text, expected_style=style)
                report["runs"].append(row)
                return read(window, pane, VOICE, row, **options)

            # An unmarked declarative reply and the very same text marked as narration
            # exercise both sides of the style choice independently of punctuation.
            cold = case("cold", narration, "reference")
            pid = cold.row["pid"]
            require(pid, "Cold read did not leave a resident")
            apps = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,gpu_uuid",
                                            "--format=csv,noheader,nounits"], text=True, timeout=10)
            devices = [line.split(",", 1)[1].strip() for line in apps.splitlines()
                       if line.partition(",")[0].strip() == str(pid)]
            require(devices, f"Resident PID {pid} missing from NVIDIA compute processes")
            report["resident_gpu_uuids"] = devices
            warm_times = []
            for name in ("warm", "warm_2", "warm_3"):
                warm = case(name, narration, "reference")
                require(warm.row["pid"] == pid, f"{name} replaced the resident")
                warm_times.append(warm.row["first_sound_s"])
            report["warm"] = dict(pid=pid, first_sound_s=warm_times, median_first_sound_s=median(warm_times))
            stopped = case("stop_queued_narration", narration, "sobre", narration=True, stop=True)
            stopped.row["warm_pid"] = pid
            require(stopped.row["pid"] == pid, "Cooperative stop did not preserve the warm resident PID")
            resumed = case("mixed_question_after_stop", mixed, "reference", narration=True)
            require(resumed.row["pid"] == pid, "Subsequent reading did not reuse the stopped resident")
            VOICE.close()
            require(not VOICE.pid, "Resident still active before fallback")
            with patch.dict(os.environ, AKASHA_VRAM_LIMIT_MIB="0"):
                report["fallback_vram_limit_mib"] = int(os.environ["AKASHA_VRAM_LIMIT_MIB"])
                case("zero_vram_piper", question, fallback=True)
            stopped.verify_closed()  # Old device remained closed through both subsequent reads.
        finally:
            try:
                VOICE.close()
            finally:
                window.destroy()


def main():
    report = dict(passed=False, onset="First 10 ms window >= -50 dBFS RMS; first observed device cursor past onset",
                  runs=[])
    try:
        run(report)
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        pending = REPORT.with_suffix(".tmp")
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending.replace(REPORT)
        print(REPORT, flush=True)


if __name__ == "__main__":
    main()
