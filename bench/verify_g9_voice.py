"""Rejoue une même consigne comme donnée G7, import G9 et dictée dans le bureau Windows."""

import argparse
import ctypes as ct
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
from tempfile import TemporaryDirectory
import time
import tkinter as tk
from unittest.mock import Mock, patch
import wave

from akasha_brain import desktop_voice
from akasha_brain.desktop_sessions import ConversationWorkspace
from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain.desktop_voice import Microphone


def spoken_file(project):
    # Le synthétiseur français de Windows fournit une entrée reproductible sans enregistrer la pièce.
    script = """
Add-Type -AssemblyName System.Speech
$tts = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $fr = $tts.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'fr-*' } |
        Select-Object -First 1
    if (-not $fr) { throw 'Voix Windows française absente' }
    $tts.SelectVoice($fr.VoiceInfo.Name)
    $audio = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, 'Sixteen', 'Mono')
    $tts.SetOutputToWaveFile((Join-Path (Get-Location) 'consigne.wav'), $audio)
    $tts.Speak('Transcris le fichier silence.')
} finally { $tts.Dispose() }
"""
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "$ErrorActionPreference = 'Stop'\n" + script], cwd=project, check=True, timeout=45)
    return project / "consigne.wav"


def wait(window, done):
    deadline = time.monotonic() + 420
    while not done():
        if time.monotonic() >= deadline:
            raise TimeoutError("Le bureau n’a pas terminé la transcription.")
        window.update()
        time.sleep(.04)
    window.update()


def controlled_microphone(pcm):
    """Émule seulement WinMM. Le tampon, sa finalisation et son effacement restent ceux du bureau."""
    api = Mock()
    for name in ("waveInOpen", "waveInPrepareHeader", "waveInStart", "waveInReset",
                 "waveInUnprepareHeader", "waveInClose"):
        getattr(api, name).return_value = 0

    def fill(_handle, pointer, size):
        assert size == ct.sizeof(desktop_voice.WaveHeader)
        header = ct.cast(pointer, ct.POINTER(desktop_voice.WaveHeader)).contents
        assert len(pcm) <= header.size
        ct.memmove(header.data, pcm, len(pcm))
        header.recorded = len(pcm)
        return 0

    api.waveInAddBuffer.side_effect = fill
    return Microphone(api)


def verify(root):
    project = root / "projet"
    project.mkdir()
    sample = spoken_file(project)
    with wave.open(str(sample), "rb") as stream:
        assert stream.getparams()[:3] == (1, 2, 16000)
        pcm = stream.readframes(stream.getnframes())
    with wave.open(str(project / "silence.wav"), "wb") as silence:
        silence.setparams((1, 2, 16000, 0, "NONE", ""))
        silence.writeframes(bytes(32000))
    window = tk.Tk()
    window.title("Akasha · Rejeu G9")
    window.geometry("900x520")
    try:
        tasks = NotesTasks(root / "runs", None, None, False)
        workspace = ConversationWorkspace(window, None, None, None, None, tasks, project=project, review_prepared=None)
        pane = workspace.current
        window.update()
        submit, = [w for w in pane.entry.master.winfo_children() if w.winfo_class() == "TButton"
                   and w.cget("text") == "Envoyer"]
        pane.entry.insert(0, "Transcris consigne.wav")
        submit.invoke()
        wait(window, lambda: pane.intent_job is None)
        analyzed = pane.transcript.get("1.0", "end").strip()
        assert "silence" in analyzed.casefold() and "Transcription · " in analyzed, analyzed
        original_plan = pane.conversation_plan
        assert original_plan.inputs == (sample.name,) and original_plan.capability == "audio.transcribe"
        assert analyzed.count("Vous\n") == 1 and not pane.entry.get()
        print("G7 terminé", flush=True)

        voice = pane.voice
        with patch.object(desktop_voice.filedialog, "askopenfilename", return_value=str(sample)):
            voice.import_button.invoke()
        wait(window, lambda: voice.job is None)
        imported = pane.entry.get()
        assert imported and "silence" in imported.casefold() and imported in analyzed, (imported, voice.status.get())
        assert pane.conversation_plan is original_plan and pane.transcript.get("1.0", "end").strip() == analyzed
        voice.erase_button.invoke()
        assert not pane.entry.get()
        print("Import G9 terminé", flush=True)

        with patch.object(desktop_voice.messagebox, "askyesno", return_value=False), patch.object(
                desktop_voice, "Microphone") as denied_device:
            voice.record.invoke()
        denied_device.assert_not_called()
        assert voice.mic is None and "refusé" in voice.status.get()
        devices = []

        def open_controlled():
            device = controlled_microphone(pcm)
            devices.append(device)
            return device

        with patch.object(desktop_voice.messagebox, "askyesno", return_value=True), patch.object(
                desktop_voice, "Microphone", side_effect=open_controlled):
            voice.record.invoke()
            voice.cancel_button.invoke()
            assert voice.job is None and not pane.entry.get()
            voice.record.invoke()
            voice.record.invoke()
        assert len(devices) == 2
        for device in devices:
            device.api.waveInClose.assert_called_once()
            assert bytes(device.buffer) == bytes(len(device.buffer))
        wait(window, lambda: voice.job is None)
        dictated = pane.entry.get()
        assert dictated == imported, (dictated, imported, voice.status.get())
        assert pane.conversation_plan is original_plan and pane.transcript.get("1.0", "end").strip() == analyzed
        first_id = pane.session_record.id
        workspace.new()
        window.update()
        assert not workspace.current.entry.get()
        workspace.select(first_id)
        window.update()
        assert workspace.current.entry.get() == dictated
        # Une correction explicite désigne le nom réel du second enregistrement.
        edited = "Transcris silence.wav"
        pane.entry.delete(0, "end")
        pane.entry.insert(0, edited)
        assert pane.transcript.get("1.0", "end").strip() == analyzed
        submit.invoke()
        wait(window, lambda: pane.intent_job is None)
        content = pane.transcript.get("1.0", "end").strip()
        assert pane.conversation_plan.inputs == ("silence.wav",)
        assert content.count("Vous\n") == 2 and f"Vous\n{edited}\n" in content
        assert "Silence. Aucun texte." in content and not pane.entry.get()
        return {"windows": platform.platform(), "audio_sha256": sha256(sample.read_bytes()).hexdigest(),
                "spoken": "Transcris le fichier silence.", "analysis": analyzed,
                "imported_draft": imported, "dictated_draft": dictated, "sent": edited,
                "conversation": content, "session_isolation": True, "cancel_and_erase": True,
                "microphone": "Accord d’application refusé puis accepté. PCM injecté dans le tampon WinMM simulé. "
                              "Arrêt, annulation, effacement et conversion WAV exercés. Aucun micro physique ouvert.",
                "file_picker": "Sélection du fichier automatisée", "interim_conversation_changes": 0}
    finally:
        window.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="akasha-g9-rejeu-") as folder:
        report = verify(Path(folder))
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
