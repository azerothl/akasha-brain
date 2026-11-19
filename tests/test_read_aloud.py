from io import BytesIO
import wave

import pytest

from akasha_brain.desktop_read_aloud import passages
from akasha_brain import desktop_read_aloud
from akasha_brain.piper_voice import MAX_TEXT, spoken_text, validate_wav
from akasha_brain.voice_style import reply_style


def test_long_replies_keep_all_words_in_order():
    text = ("Voici le résultat. " * 240).strip()
    chunks = list(passages(text))
    assert len(chunks) > 1 and all(0 < len(c) <= MAX_TEXT for c in chunks)
    assert " ".join(chunks) == text
    assert "".join(passages("x"*(MAX_TEXT+31))) == "x"*(MAX_TEXT+31)


def test_one_direction_for_the_entire_reply_and_reference_by_default():
    assert reply_style("Le dossier est prêt.") == "reference"
    assert reply_style("Le dossier est prêt.", narration_only=True) == "sobre"
    mixed = "Le dossier est prêt. " * 30 + "Je te l’envoie ?"
    assert len(list(passages(mixed, 220))) > 1
    assert reply_style(mixed, narration_only=True) == "reference"


def test_gpu_can_fall_back_only_before_playback(monkeypatch):
    events = []

    class Device:
        def __init__(self, check, start):
            self.start = start

        def __enter__(self):
            return self

        def write(self, block):
            self.start()

        def __exit__(self, *args):
            events.append("close")

    def unavailable(*args):
        raise desktop_read_aloud.qwen_resident.QwenUnavailable("GPU absent")

    monkeypatch.setattr(desktop_read_aloud.stream_audio, "PCMOutput", Device)
    monkeypatch.setattr(desktop_read_aloud.qwen_resident.VOICE, "stream", unavailable)
    play = lambda: desktop_read_aloud.play_vivian("Bonjour.", "reference", lambda: None, lambda: events.append("play"))
    assert not play() and events == []

    def disconnected(text, style, check, write):
        write(b"\x01\x00" * 100)
        unavailable()

    monkeypatch.setattr(desktop_read_aloud.qwen_resident.VOICE, "stream", disconnected)
    with pytest.raises(RuntimeError, match="interrompue pendant la lecture"):
        play()
    assert events == ["play", "close"]


def test_pronunciation_changes_only_recognized_initialisms():
    assert spoken_text("Le TGV de la SNCF.\nCamille Martin.") == "Le T G V de la S N C F. Camille Martin."
    assert spoken_text("TGVX et TVA") == "TGVX et T V A"


def wav(payload, rate):
    destination = BytesIO()
    with wave.open(destination, "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", ""))
        stream.writeframes(payload)
    return destination.getvalue()


def test_audio_output_requires_complete_non_silent_pcm_at_voice_rate():
    data = wav(b"\x12\x00"*22050, 22050)
    assert validate_wav(data) == 1
    for invalid in (data[:-2], wav(bytes(44), 22050), wav(b"\x12\x00"*100, 16000)):
        with pytest.raises(ValueError):
            validate_wav(invalid)
