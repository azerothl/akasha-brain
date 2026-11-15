"""Observer la fenêtre Notes et contrôler sa base dans le bac."""

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import sqlite3
from time import sleep

from measure_ocr import fold

TITLE = "Note Akasha"
CONTENT = "Contenu durable"


def window_api():
    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user.WindowFromPoint.argtypes = (wintypes.POINT,)
    user.WindowFromPoint.restype = wintypes.HWND
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    return user


def owned_by(user, window, pid: int) -> bool:
    owner = wintypes.DWORD()
    return bool(window and user.GetWindowThreadProcessId(window, ctypes.byref(owner)) and owner.value == pid)


def observe(user, pid: int, engine):
    from PIL import Image, ImageGrab

    window = user.GetForegroundWindow()
    rect = wintypes.RECT()
    if not owned_by(user, window, pid) or not user.GetWindowRect(window, ctypes.byref(rect)):
        raise RuntimeError("La fenêtre Notes attendue ne possède plus le focus.")
    image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
    enlarged = image.resize((2 * image.width, 2 * image.height), Image.Resampling.BICUBIC)
    import numpy as np

    # RapidOCR attend BGR pour un tableau issu d'OpenCV.
    results, _ = engine(np.asarray(enlarged)[:, :, ::-1].copy())
    return rect, results or []


def click(user, pid: int, rect, box) -> None:
    x = rect.left + round(sum(point[0] for point in box) / (2 * len(box)))
    y = rect.top + round(sum(point[1] for point in box) / (2 * len(box)))
    if not owned_by(user, user.GetForegroundWindow(), pid) or not owned_by(
        user, user.WindowFromPoint(wintypes.POINT(x, y)), pid
    ):
        raise RuntimeError("La position OCR est hors de la fenêtre Notes.")
    if not user.SetCursorPos(x, y):
        raise RuntimeError("Position OCR inaccessible.")
    user.mouse_event(0x0002, 0, 0, 0, 0)
    user.mouse_event(0x0004, 0, 0, 0, 0)


def read_notes(pid: int, action: str) -> int:
    from rapidocr_onnxruntime import RapidOCR

    user = window_api()
    engine = RapidOCR()
    sessions = (engine.text_det.infer, engine.text_cls.infer, engine.text_rec.session)
    if any(session.session.get_providers() != ["CPUExecutionProvider"] for session in sessions):
        return 5
    rect, results = observe(user, pid, engine)
    if action == "save":
        matches = [box for box, text, _ in results if fold(text) == "enregistrer"]
        if len(matches) != 1:
            return 6
        click(user, pid, rect, matches[0])
        return 0
    wanted = fold(TITLE)
    matches = [box for box, text, _ in results if fold(text) == wanted or fold(text).endswith(" " + wanted)]
    if len(matches) != 1:
        return 7
    click(user, pid, rect, matches[0])
    sleep(0.3)
    _, restored = observe(user, pid, engine)
    return 0 if any(fold(text) == fold(CONTENT) for _, text, _ in restored) else 8


def verify_sqlite(database: Path) -> int:
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id, title, content FROM notes").fetchall()
    return 0 if len(rows) == 1 and rows[0][0] > 0 and rows[0][1:] == (TITLE, CONTENT) else 9


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("save", "restore", "sqlite"))
    parser.add_argument("target")
    parser.add_argument("--error-log", type=Path, required=True)
    args = parser.parse_args()
    try:
        code = verify_sqlite(Path(args.target)) if args.action == "sqlite" else read_notes(int(args.target), args.action)
    except (ImportError, OSError, RuntimeError, ValueError, AttributeError, sqlite3.Error) as error:
        args.error_log.write_text(f"{type(error).__name__}: {error}", encoding="ascii", errors="replace")
        code = 1
    raise SystemExit(code)
