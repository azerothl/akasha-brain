"""Dictée Windows et import vocal dans le champ de saisie de la conversation."""

from concurrent.futures import Future, TimeoutError
import ctypes as ct
from datetime import datetime
from pathlib import Path
from queue import Empty, SimpleQueue
from tempfile import TemporaryDirectory
from threading import Event
from tkinter import StringVar, filedialog, messagebox, ttk
import wave

from . import whisper_pilot
from .project_approval import require_fresh
from .project_common import project_scope
from .whisper_recovery import describe


class WaveFormat(ct.Structure):
    _pack_ = 1
    _fields_ = [("format", ct.c_uint16), ("channels", ct.c_uint16), ("rate", ct.c_uint32),
                ("bytes_per_second", ct.c_uint32), ("align", ct.c_uint16), ("bits", ct.c_uint16),
                ("extra", ct.c_uint16)]


class WaveHeader(ct.Structure):
    _fields_ = [("data", ct.c_void_p), ("size", ct.c_uint32), ("recorded", ct.c_uint32),
                ("user", ct.c_size_t), ("flags", ct.c_uint32), ("loops", ct.c_uint32),
                ("next", ct.c_void_p), ("reserved", ct.c_size_t)]


class Microphone:
    """Une seule mémoire PCM de deux minutes, rendue par WinMM à l'arrêt."""

    def __init__(self, api=None):
        self.api = api if api is not None else ct.WinDLL("winmm", winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
        self.handle = ct.c_void_p()
        self.buffer = ct.create_string_buffer(120 * 16000 * 2)
        self.header = WaveHeader(ct.addressof(self.buffer), len(self.buffer))
        self.prepared = False
        fmt = WaveFormat(1, 1, 16000, 32000, 2, 16, 0)
        self.check(self.api.waveInOpen(ct.byref(self.handle), -1, ct.byref(fmt), 0, 0, 0))
        try:
            self.check(self.header_call(self.api.waveInPrepareHeader))
            self.prepared = True
            self.check(self.header_call(self.api.waveInAddBuffer))
            self.check(self.api.waveInStart(self.handle))
        except OSError:
            self.close()
            raise

    def check(self, code):
        if code:
            reason = ct.create_unicode_buffer(256)
            self.api.waveInGetErrorTextW(code, reason, len(reason))
            raise OSError(f"Microphone inaccessible ({code}). {reason.value}")

    def header_call(self, function):
        return function(self.handle, ct.byref(self.header), ct.sizeof(self.header))

    def close(self, *, keep=False):
        try:
            self.check(self.api.waveInReset(self.handle))
            if keep:
                return bytearray(memoryview(self.buffer).cast("B")[:self.header.recorded])
        finally:
            try:
                if self.prepared:
                    self.check(self.header_call(self.api.waveInUnprepareHeader))
            finally:
                self.check(self.api.waveInClose(self.handle))
                ct.memset(self.buffer, 0, len(self.buffer))


class VoiceRequest:
    """Possède le contexte, l'annulation et les accords d'une seule transcription."""

    def __init__(self, project):
        self.project = project
        self.scope = project_scope(project) if project is not None else None
        self.cancelled = Event()
        self.updates = SimpleQueue()
        self.pcm = None

    def discard_capture(self):
        pcm, self.pcm = self.pcm, None
        if pcm is not None:
            pcm[:] = bytes(len(pcm))

    def cancel(self):
        self.cancelled.set()
        self.discard_capture()

    def checkpoint(self):
        if self.cancelled.is_set():
            raise InterruptedError("Demande vocale annulée.")
        if self.project is not None and project_scope(self.project) != self.scope:
            raise ValueError("Le dossier de projet a changé.")

    def approve(self, review):
        decision = Future()
        self.updates.put((review, decision))
        while True:
            self.checkpoint()
            require_fresh(datetime.fromisoformat(review.expires_at))
            try:
                answer = decision.result(timeout=.1)
            except TimeoutError:
                continue
            require_fresh(datetime.fromisoformat(review.expires_at))
            self.checkpoint()
            return answer

    def transcribe(self, project, name):
        self.checkpoint()
        result = whisper_pilot.transcribe(project, name, self.checkpoint, ask=self.approve, progress=self.updates.put)
        self.checkpoint()
        return result

    def from_capture(self):
        self.checkpoint()
        with TemporaryDirectory(prefix="akasha-dictee-") as scratch:
            folder = Path(scratch)
            with wave.open(str(folder / "dictee.wav"), "wb") as stream:
                stream.setparams((1, 2, 16000, 0, "NONE", ""))
                pcm = self.pcm
                self.checkpoint()
                stream.writeframes(pcm)
            self.discard_capture()
            return self.transcribe(folder, "dictee.wav")


class VoiceComposer:
    def __init__(self, page, pane):
        self.pane = pane
        self.request = self.mic = self.job = self.timer = None
        self.draft = False
        self.bar = ttk.Frame(page, style="Data.TFrame")
        self.bar.pack(fill="x", pady=(6, 0))
        self.record = ttk.Button(self.bar, text="Dicter au micro", command=self.toggle_microphone)
        self.record.pack(side="left")
        self.import_button = ttk.Button(self.bar, text="Importer un message vocal…", command=self.choose_file)
        self.import_button.pack(side="left", padx=4)
        self.cancel_button = ttk.Button(self.bar, text="Annuler", command=self.cancel)
        self.erase_button = ttk.Button(self.bar, text="Effacer le brouillon", command=self.erase)
        self.status = StringVar(master=page)
        ttk.Label(page, textvariable=self.status, style="DataMuted.TLabel", wraplength=680).pack(fill="x")
        self.bar.bind("<Unmap>", self.hidden)
        self.bar.bind("<Destroy>", self.destroyed)

    def sent(self):
        if self.draft:
            self.draft = False
            self.erase_button.pack_forget()
            if self.request is None:
                self.status.set("")

    def hidden(self, _event):
        if self.request is not None:
            self.cancel()

    def destroyed(self, _event):
        self.release()

    def release(self):
        if self.timer is not None:
            self.bar.after_cancel(self.timer)
            self.timer = None
        if self.request is not None:
            self.request.cancel()
            self.request = None
        if self.job is not None:
            self.job.cancel()
            self.job = None
        if self.mic is not None:
            mic, self.mic = self.mic, None
            mic.close()

    def idle(self, message):
        self.record.configure(text="Dicter au micro", state="normal")
        self.import_button.state(["!disabled"])
        self.cancel_button.pack_forget()
        self.status.set(message)

    def cancel(self):
        try:
            self.release()
        except OSError as error:
            self.idle(str(error))
        else:
            self.idle("Demande vocale annulée.")

    def erase(self):
        self.cancel()
        if self.draft:
            self.pane.entry.delete(0, "end")
            self.sent()
        self.status.set("")

    def begin(self):
        self.request = VoiceRequest(self.pane.project)
        self.import_button.state(["disabled"])
        self.cancel_button.pack(side="left")
        return self.request

    def choose_file(self):
        if self.request is not None:
            return
        if self.pane.project is None and not self.pane.choose_project():
            return
        project = self.pane.project
        name = filedialog.askopenfilename(parent=self.bar, title="Message vocal du projet",
                                          initialdir=project, filetypes=[("WAV ou FLAC", "*.wav *.flac")])
        if not name:
            return
        try:
            relative = Path(name).relative_to(project).as_posix()
        except ValueError:
            self.status.set("Choisissez un enregistrement dans le projet actif.")
            return
        try:
            request = self.begin()
            self.submit(request.transcribe, project, relative)
        except (OSError, RuntimeError, ValueError) as error:
            self.cancel()
            self.status.set(str(error))

    def toggle_microphone(self):
        try:
            if self.mic is not None:
                self.bar.after_cancel(self.timer)
                self.timer = None
                mic, self.mic = self.mic, None
                self.request.pcm = mic.close(keep=True)
                self.submit(self.request.from_capture)
            elif self.request is None:
                if not messagebox.askyesno("Dicter une demande", "Autoriser le micro pour cette dictée ?",
                                           parent=self.bar, default="no"):
                    self.status.set("Accès au micro refusé.")
                    return
                self.begin()
                self.mic = Microphone()
                self.record.configure(text="Terminer la dictée")
                self.status.set("Micro ouvert. La dictée s’arrête après deux minutes.")
                self.timer = self.bar.after(120000, self.toggle_microphone)
        except (OSError, RuntimeError, ValueError, AttributeError) as error:
            self.cancel()
            self.status.set(str(error))

    def submit(self, operation, *args):
        self.record.state(["disabled"])
        self.status.set("Transcription en cours…")
        self.job = self.pane.tasks.scheduler.submit(lambda: operation(*args))
        self.timer = self.bar.after(80, self.poll)

    def poll(self):
        self.timer = None
        request = self.request
        try:
            request.checkpoint()
            while not self.job.done():
                try:
                    update = request.updates.get_nowait()
                except Empty:
                    break
                if isinstance(update, tuple):
                    review, decision = update
                    answer = messagebox.askyesnocancel("Téléchargement Whisper", describe(review),
                                                      parent=self.bar, default="no")
                    if self.request is not request:
                        return
                    decision.set_result({True: "accept", False: "decline", None: "cancel"}[answer])
                else:
                    self.status.set(update)
            if not self.job.done():
                self.timer = self.bar.after(80, self.poll)
                return
            result = self.job.result()
            request.checkpoint()
            self.release()
            if not result["text"].strip():
                self.idle("Aucune parole transcrite.")
                return
            previous = self.pane.entry.get()
            separator = " " if previous and not previous[-1].isspace() else ""
            self.pane.entry.insert("end", separator + result["text"].strip())
            self.draft = True
            self.erase_button.pack(side="left")
            self.pane.entry.icursor("end")
            self.pane.focus()
            self.idle("Relisez le brouillon puis choisissez Envoyer.")
        except Exception as error:
            self.cancel()
            self.status.set(str(error))
