"""Commandes Tk pour la lecture de la réponse affichée."""

from concurrent.futures import Future, TimeoutError
from contextlib import ExitStack
from queue import Empty, SimpleQueue
from threading import Event, Thread
from tkinter import messagebox, ttk

from . import piper_voice, qwen_resident, stream_audio
from .voice_style import reply_style
from .whisper_recovery import describe


def passages(text, limit=piper_voice.MAX_TEXT):
    remaining = text.strip()
    while len(remaining) > limit:
        cut = max(remaining.rfind(c, 0, limit) for c in ".!?…\n") + 1
        if cut <= 0:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        yield remaining[:cut].strip()
        remaining = remaining[cut:].lstrip()
    if remaining:
        yield remaining


def play_vivian(text, style, check, playing):
    """Le premier bloc ouvre la sortie. Une annulation vide aussi les blocs déjà soumis."""
    with ExitStack() as devices:
        output = None
        submitted = False

        def checkpoint():
            try:
                check()
            except InterruptedError:
                devices.close()
                raise

        def on_start():
            nonlocal submitted
            submitted = True
            playing()

        def write(block):
            nonlocal output
            checkpoint()
            if output is None:
                output = devices.enter_context(stream_audio.PCMOutput(checkpoint, on_start))
            output.write(block)

        try:
            for part in passages(text, 220):
                checkpoint()
                qwen_resident.VOICE.stream(part, style, checkpoint, write)
            if output is None:
                raise qwen_resident.QwenUnavailable("La voix GPU n’a fourni aucun son.")
            output.drain()
        except qwen_resident.QwenUnavailable as error:
            checkpoint()
            if submitted:
                raise RuntimeError("La voix GPU a été interrompue pendant la lecture.") from error
            return False
        return True


class ReplyReader:
    def __init__(self, parent, scheduler, project):
        self.scheduler = scheduler
        self.project = project
        self.text = ""
        self.style = "reference"
        self.cancelled = Event()
        self.events = SimpleQueue()
        self.worker = None
        self.bar = ttk.Frame(parent)
        self.bar.pack(fill="x")
        self.read_button = ttk.Button(self.bar, text="Lire la réponse", command=self.start, state="disabled")
        self.read_button.pack(side="left")
        self.stop_button = ttk.Button(self.bar, text="Arrêter", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        self.status = ttk.Label(self.bar, text="")
        self.status.pack(side="left", padx=6)
        self.bar.bind("<Unmap>", lambda _: self.stop(), add="+")
        self.bar.bind("<Destroy>", lambda _: self.cancelled.set(), add="+")

    def set_text(self, text, *, narration_only=False):
        self.text = text
        self.style = reply_style(text, narration_only)
        if self.worker is None:
            self.read_button.configure(state="normal" if text.strip() else "disabled")

    def stop(self):
        if self.worker is not None:
            self.cancelled.set()
            self.status.configure(text="Arrêt en cours…")

    def start(self):
        if self.worker is not None or not self.text.strip():
            return
        self.cancelled = cancelled = Event()
        text, project, style = self.text, self.project(), self.style
        self.read_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.configure(text="Préparation de la lecture…")

        def check():
            if cancelled.is_set():
                raise InterruptedError("Lecture arrêtée.")

        def ask(review):
            answer = Future()
            self.events.put(("ask", (review, answer)))
            while True:
                check()
                try:
                    return answer.result(timeout=.1)
                except TimeoutError:
                    continue

        def work():
            try:
                if not play_vivian(text, style, check, lambda: self.events.put(("playing", "Vivian · GPU"))):
                    self.events.put(("fallback", None))
                    self.play_piper(text, project, check, ask, cancelled)
                check()
                message = "Lecture terminée."
            except InterruptedError:
                message = "Lecture arrêtée."
            except Exception as error:
                message = f"Lecture interrompue. {error}"
            self.events.put(("done", message))

        self.worker = Thread(target=work, name="Lecture de la réponse", daemon=False)
        self.worker.start()
        self.bar.after(40, self.poll)

    def play_piper(self, text, project, check, ask, cancelled):
        for part in passages(text):
            check()
            job = self.scheduler.submit(lambda: piper_voice.synthesize(part, check, ask=ask, project=project))
            while True:
                try:
                    data, _ = job.result(timeout=.1)
                    break
                except TimeoutError:
                    if cancelled.is_set() and job.cancel():
                        check()
                    if job.done():
                        data, _ = job.result()
                        break
            check()
            piper_voice.play_wav(data, check, lambda: self.events.put(("playing", "Piper · CPU")))

    def poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except Empty:
                break
            if kind == "ask":
                review, answer = value
                approved = not self.cancelled.is_set() and messagebox.askyesno(
                    "Téléchargement de la voix française", describe(review), parent=self.bar)
                answer.set_result("accept" if approved else "decline")
            elif kind == "playing" and not self.cancelled.is_set():
                self.status.configure(text=f"Lecture en cours · {value}")
            elif kind == "fallback" and not self.cancelled.is_set():
                self.status.configure(text="Préparation de la voix de repli · Piper CPU…")
            elif kind == "done":
                self.worker = None
                self.status.configure(text=value)
                self.stop_button.configure(state="disabled")
                self.read_button.configure(state="normal" if self.text.strip() else "disabled")
                return
        self.bar.after(40, self.poll)
