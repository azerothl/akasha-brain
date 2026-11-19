import ctypes as ct

import pytest

from akasha_brain import stream_audio as audio


class WaveDevice:
    """Simulates driver ownership using raw addresses, without retaining Python buffers."""

    def __init__(self):
        self.open = False
        self.prepared = set()
        self.queued = []
        self.played = bytearray()
        self.peak_bytes = 0
        self.resets = 0
        self.unit = 2
        self.cursor = 0
        self.fail = None

    def waveOutOpen(self, handle, mapper, fmt, callback, instance, flags):
        assert not self.open and mapper == 0xffffffff and callback == instance == flags == 0
        fmt = ct.cast(fmt, ct.POINTER(audio._WaveFormat)).contents
        assert (fmt.tag, fmt.channels, fmt.rate, fmt.bytes_per_second, fmt.align, fmt.bits, fmt.extra) == (
            1, 1, 24_000, 48_000, 2, 16, 0)
        if self.fail == "open":
            return 2
        self.open = True
        ct.cast(handle, ct.POINTER(ct.c_void_p))[0] = 123
        return 0

    def waveOutPrepareHeader(self, handle, pointer, size):
        assert self.open and handle == 123
        header = ct.cast(pointer, ct.POINTER(audio._WaveHeader)).contents
        assert size == ct.sizeof(header) and header.flags == 0
        if self.fail == "prepare":
            return 7
        self.prepared.add(ct.addressof(header))
        header.flags = 2
        return 0

    def waveOutWrite(self, handle, pointer, size):
        header = ct.cast(pointer, ct.POINTER(audio._WaveHeader)).contents
        address = ct.addressof(header)
        assert self.open and address in self.prepared
        if self.fail == "write":
            return 7
        self.queued.append(address)
        pending = sum(audio._WaveHeader.from_address(addr).length for addr in self.queued)
        self.peak_bytes = max(self.peak_bytes, pending)
        return 0

    def complete_one(self):
        header = audio._WaveHeader.from_address(self.queued.pop(0))
        self.played.extend(ct.string_at(header.data, header.length))
        header.flags |= 1

    def waveOutUnprepareHeader(self, handle, pointer, size):
        address = ct.cast(pointer, ct.c_void_p).value
        assert self.open and address not in self.queued
        self.prepared.remove(address)
        return 0

    def waveOutReset(self, handle):
        assert self.open
        for address in self.queued:
            audio._WaveHeader.from_address(address).flags |= 1
        self.queued.clear()
        self.resets += 1
        return 0

    def waveOutClose(self, handle):
        assert self.open and not self.prepared and not self.queued
        self.open = False
        return 0

    def waveOutGetPosition(self, handle, pointer, size):
        assert self.open and handle == 123 and size == 12
        time = ct.cast(pointer, ct.POINTER(audio._MMTime)).contents
        assert time.unit == 2
        time.unit, time.value = self.unit, self.cursor
        return 0


@pytest.fixture
def device(monkeypatch):
    driver = WaveDevice()
    monkeypatch.setattr(audio, "_load_winmm", lambda: driver)
    monkeypatch.setattr(audio, "sleep", lambda _: pytest.fail("Unexpected wait for the device"))
    return driver


def test_incremental_submission_and_bounded_drain(device, monkeypatch):
    starts = []
    pcm = bytes(range(256)) * 500
    with audio.PCMOutput(lambda: None, lambda: starts.append(len(device.queued))) as out:
        assert not out.closed and out.device == 123
        out.write(b"")
        assert not starts
        out.write(pcm[:2])
        assert starts == [1] and not device.played
        device.complete_one()
        monkeypatch.setattr(audio, "sleep", lambda _: device.complete_one())
        out.write(pcm[2:])
        assert 0 < device.peak_bytes <= 7680  # Four 40 ms buffers at 24 kHz.
        assert len(device.played) < len(pcm)
        out.drain()
        out.drain()
        assert device.played == pcm and starts == [1]
    assert out.closed and out.device is None and not device.open
    assert device.resets == 0
    out.close()


@pytest.mark.parametrize(("unit", "cursor", "frames"), [(2, 239, 239), (4, 478, 239), (1, 10, 240)])
def test_position_reports_hardware_progress(device, unit, cursor, frames):
    with audio.PCMOutput(lambda: None, lambda: None) as out:
        out.write(bytes(1000))
        assert out.position_frames() == 0
        device.unit, device.cursor = unit, cursor
        assert out.position_frames() == frames
        device.unit = 8
        with pytest.raises(OSError):
            out.position_frames()
    with pytest.raises(RuntimeError):
        out.position_frames()
    assert out.closed and not device.open


class Cancelled(Exception):
    pass


@pytest.mark.parametrize("waiting", ["queue", "drain"])
def test_cancel_while_device_stops_advancing(device, monkeypatch, waiting):
    waits = []

    def checkpoint():
        if waits:
            raise Cancelled

    def stalled(seconds):
        assert 0 < seconds <= 0.04 and not waits
        waits.append(seconds)

    monkeypatch.setattr(audio, "sleep", stalled)
    with pytest.raises(Cancelled):
        with audio.PCMOutput(checkpoint, lambda: None) as out:
            out.write(bytes(20_000) if waiting == "queue" else bytes(2))
            out.drain()
    assert waits and device.resets == 1 and not device.played
    assert out.closed and not device.open


@pytest.mark.parametrize("exit_kind", ["normal", "producer", "on_start"])
def test_leave_without_drain_discards_audio_immediately(device, exit_kind):
    def started():
        if exit_kind == "on_start":
            assert device.queued
            raise Cancelled

    def play():
        with out:
            out.write(bytes(40))
            if exit_kind == "producer":
                raise Cancelled

    out = audio.PCMOutput(lambda: None, started)
    if exit_kind == "normal":
        play()
    else:
        with pytest.raises(Cancelled):
            play()
    assert out.closed and not device.open and device.resets == 1 and not device.played


@pytest.mark.parametrize("failure", ["open", "prepare", "write"])
def test_device_errors_release_resources_without_announcing_start(device, failure):
    device.fail = failure
    out = audio.PCMOutput(lambda: None, lambda: pytest.fail("No PCM was submitted"))
    with pytest.raises(OSError):
        with out:
            out.write(bytes(10))
    assert out.closed and not device.open and not device.prepared


@pytest.mark.parametrize("failure", ["prepare", "write"])
def test_late_device_error_discards_earlier_submission(device, failure):
    starts = []
    with pytest.raises(OSError):
        with audio.PCMOutput(lambda: None, lambda: starts.append(True)) as out:
            out.write(bytes(2))
            device.fail = failure
            out.write(bytes(2))
    assert starts == [True] and device.resets == 1 and not device.played
    assert out.closed and not device.open and not device.prepared


def test_partial_frame_rejected_before_submission(device):
    with pytest.raises(ValueError):
        with audio.PCMOutput(lambda: None, lambda: pytest.fail("No complete frame")) as out:
            out.write(b"x")
    assert out.closed and not device.open and not device.played
