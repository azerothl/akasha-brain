"""Incremental Windows playback for the resident voice's 24 kHz mono PCM."""

import ctypes as ct
from collections import deque
from threading import Lock
from time import sleep


SAMPLE_RATE = 24_000
FRAME_BYTES = 2
BLOCK_BYTES = SAMPLE_RATE * FRAME_BYTES // 25  # 40 ms
MAX_HEADERS = 4
POLL_SECONDS = 0.01
WHDR_DONE = 1
TIME_MS, TIME_SAMPLES, TIME_BYTES = 1, 2, 4


class _WaveFormat(ct.Structure):
    _pack_ = 1
    _fields_ = [("tag", ct.c_uint16), ("channels", ct.c_uint16), ("rate", ct.c_uint32),
                ("bytes_per_second", ct.c_uint32), ("align", ct.c_uint16),
                ("bits", ct.c_uint16), ("extra", ct.c_uint16)]


class _WaveHeader(ct.Structure):
    _fields_ = [("data", ct.POINTER(ct.c_char)), ("length", ct.c_uint32),
                ("recorded", ct.c_uint32), ("user", ct.c_size_t), ("flags", ct.c_uint32),
                ("loops", ct.c_uint32), ("next", ct.c_void_p), ("reserved", ct.c_size_t)]


class _MMTime(ct.Structure):
    # The largest MMTIME union member (SMPTE) occupies eight bytes.
    _fields_ = [("unit", ct.c_uint32), ("value", ct.c_uint32), ("padding", ct.c_uint32)]


def _load_winmm():
    dll = ct.WinDLL("winmm", winmode=0x800)
    handle, uint = ct.c_void_p, ct.c_uint
    header_args = (handle, ct.POINTER(_WaveHeader), uint)
    signatures = {
        "waveOutOpen": (ct.POINTER(handle), uint, ct.POINTER(_WaveFormat), ct.c_size_t, ct.c_size_t, uint),
        "waveOutPrepareHeader": header_args, "waveOutWrite": header_args,
        "waveOutUnprepareHeader": header_args,
        "waveOutGetPosition": (handle, ct.POINTER(_MMTime), uint),
        "waveOutReset": (handle,), "waveOutClose": (handle,),
    }
    for name, args in signatures.items():
        function = getattr(dll, name)
        function.argtypes = args
        function.restype = uint
    return dll


def _check(result, operation):
    if result:
        raise OSError(f"{operation} a échoué (WinMM {result}).")


class PCMOutput:
    """One producer owns write/drain/close. Another thread may sample position.

    Writes contain whole signed little-endian mono16 frames. While waiting for
    the next write the device plays autonomously. The producer owns cancellation
    checks while it waits for input. Device backpressure and drain poll checkpoint.
    """

    def __init__(self, checkpoint, on_start):
        self._checkpoint = checkpoint
        self._on_start = on_start
        self._pending = deque()
        self._handle = ct.c_void_p()
        self._position_lock = Lock()
        self._started = False

    @property
    def device(self):
        """Native HWAVEOUT value while open, otherwise None."""
        return self._handle.value

    @property
    def closed(self):
        return self.device is None

    def __enter__(self):
        if not self.closed:
            raise RuntimeError("La sortie audio est déjà ouverte.")
        self._checkpoint()
        self._api = _load_winmm()
        fmt = _WaveFormat(1, 1, SAMPLE_RATE, SAMPLE_RATE * FRAME_BYTES, FRAME_BYTES, 16, 0)
        handle = ct.c_void_p()
        _check(self._api.waveOutOpen(ct.byref(handle), 0xffffffff, ct.byref(fmt), 0, 0, 0), "waveOutOpen")
        self._handle = handle
        self._started = False
        return self

    def _require_open(self):
        if self.closed:
            raise RuntimeError("La sortie audio est fermée.")

    def position_frames(self):
        """Read the device cursor in mono frames, including during drain."""
        with self._position_lock:
            self._require_open()
            time = _MMTime(TIME_SAMPLES)
            _check(self._api.waveOutGetPosition(self.device, ct.byref(time), ct.sizeof(time)), "waveOutGetPosition")
            if time.unit == TIME_SAMPLES:
                return time.value
            if time.unit == TIME_BYTES:
                return time.value // FRAME_BYTES
            if time.unit == TIME_MS:
                return time.value * SAMPLE_RATE // 1000
            raise OSError(f"Unité de position WinMM inconnue ({time.unit}).")

    def _wait_below(self, limit):
        while True:
            self._checkpoint()
            while self._pending and self._pending[0].flags & WHDR_DONE:
                self._unprepare(self._pending[0])
                self._pending.popleft()
            if len(self._pending) < limit:
                return
            sleep(POLL_SECONDS)

    def _unprepare(self, header):
        _check(self._api.waveOutUnprepareHeader(self.device, ct.byref(header), ct.sizeof(header)),
               "waveOutUnprepareHeader")

    def write(self, pcm: bytes):
        self._require_open()
        if len(pcm) % FRAME_BYTES:
            raise ValueError("Une trame PCM mono16 requiert deux octets.")
        if not pcm:
            self._checkpoint()
            return
        view = memoryview(pcm)
        for offset in range(0, len(view), BLOCK_BYTES):
            self._wait_below(MAX_HEADERS)
            block = view[offset:offset + BLOCK_BYTES]
            # The ctypes pointer field keeps the sample array alive with the header.
            samples = (ct.c_char * len(block)).from_buffer_copy(block)
            header = _WaveHeader(samples, len(block))
            args = (self.device, ct.byref(header), ct.sizeof(header))
            _check(self._api.waveOutPrepareHeader(*args), "waveOutPrepareHeader")
            self._pending.append(header)
            result = self._api.waveOutWrite(*args)
            if result:
                self._unprepare(header)
                self._pending.pop()
                _check(result, "waveOutWrite")
            if not self._started:
                self._started = True
                self._on_start()

    def drain(self):
        self._require_open()
        self._wait_below(1)

    def close(self):
        with self._position_lock:
            if self.closed:
                return
            if self._pending:
                _check(self._api.waveOutReset(self.device), "waveOutReset")
                while self._pending:
                    self._unprepare(self._pending[0])
                    self._pending.popleft()
            _check(self._api.waveOutClose(self.device), "waveOutClose")
            self._handle = ct.c_void_p()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
