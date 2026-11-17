"""Récupère le cadre d'image affiché dans la seule fenêtre du bac."""

import ctypes
from ctypes import wintypes as win
from pathlib import PureWindowsPath
from time import sleep

from PIL import Image, ImageChops, ImageGrab


def crop_frame(screen, frame: str):
    color = bytes.fromhex(frame[1:])
    values = screen.convert("RGB").split()
    r, g, b = (channel.point(lambda value: 255 if abs(value - expected) <= 7 else 0)
               for channel, expected in zip(values, color))
    mask = ImageChops.multiply(ImageChops.multiply(r, g), b)
    rows = [index for index, density in enumerate(mask.resize((1, mask.height), Image.Resampling.BOX).tobytes())
            if density * mask.width >= 300 * 255]
    columns = [index for index, density in enumerate(mask.resize((mask.width, 1), Image.Resampling.BOX).tobytes())
               if density * mask.height >= 300 * 255]
    if not rows or not columns:
        return None
    x0, y0, x1, y1 = columns[0], rows[0], columns[-1] + 1, rows[-1] + 1
    width, height = x1 - x0, y1 - y0
    if width != height or not 432 <= width <= 1088:
        return None
    margin = round(width * 16 / 544)
    probe = margin // 2
    borders = ((x0 + probe, y0 + probe, x1 - probe, y0 + probe + 1),
               (x0 + probe, y1 - probe, x1 - probe, y1 - probe + 1),
               (x0 + probe, y0 + probe, x0 + probe + 1, y1 - probe),
               (x1 - probe, y0 + probe, x1 - probe + 1, y1 - probe))
    strips = (mask.crop(edge) for edge in borders)
    if any(area.histogram()[255] < 0.98 * area.width * area.height for area in strips):
        return None
    image = screen.crop((x0 + margin, y0 + margin, x1 - margin, y1 - margin)).convert("RGB")
    if len(image.resize((24, 24)).getcolors(576) or ()) < 24:
        return None
    return image.resize((512, 512), Image.Resampling.LANCZOS)


def sandbox_window():
    ui, kernel = ctypes.windll.user32, ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (win.DWORD, win.BOOL, win.DWORD)
    kernel.OpenProcess.restype = win.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (win.HANDLE, win.DWORD, win.LPWSTR, ctypes.POINTER(win.DWORD))
    kernel.CloseHandle.argtypes = (win.HANDLE,)
    callback = ctypes.WINFUNCTYPE(win.BOOL, win.HWND, win.LPARAM)
    found = []

    def inspect(hwnd, _):
        if not ui.IsWindowVisible(hwnd):
            return True
        process = win.DWORD()
        ui.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        handle = kernel.OpenProcess(0x1000, False, process.value)
        if handle:
            try:
                path = ctypes.create_unicode_buffer(2048)
                length = win.DWORD(len(path))
                if (kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length))
                        and PureWindowsPath(path.value).name.casefold() == "windowssandboxremotesession.exe"):
                    found.append(hwnd)
            finally:
                kernel.CloseHandle(handle)
        return True

    ui.EnumWindows(callback(inspect), 0)
    return found[0] if len(found) == 1 else None


def capture(frame: str):
    ui = ctypes.windll.user32
    hwnd = sandbox_window()
    if hwnd is None or ui.IsIconic(hwnd):
        return None
    flags = 0x0013  # Conserve la géométrie et le focus.
    ui.SetWindowPos.argtypes = (win.HWND, win.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, win.UINT)
    if not ui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags):
        return None
    try:
        rect = win.RECT()
        dwm = ctypes.windll.dwmapi
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            return None
        bounds = (rect.left, rect.top, rect.right, rect.bottom)
        if not 432 <= rect.right - rect.left <= 7680 or not 432 <= rect.bottom - rect.top <= 4320:
            return None
        sleep(0.25)
        return crop_frame(ImageGrab.grab(bbox=bounds, all_screens=True), frame)
    finally:
        ui.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)
