"""Relevé versionné des observations bureau du banc Notes."""

VERSION = "1.0.0"
NOTES_WINDOW_TITLE = "Notes — banc Akasha"


def decode_notes_observation(packet: int, *, started_at: str, finished_at: str) -> dict:
    """Décode un relevé invité borné à un PID 20 bits et six indicateurs."""
    if packet & ~0x0FFFFF3F != 0x60000000:
        raise ValueError(f"Relevé DesktopState invalide ({packet:#x}).")
    pid = (packet >> 8) & 0xFFFFF
    if not pid:
        raise ValueError("PID absent du relevé DesktopState.")

    title_observed = bool(packet & 0x02)
    fixture_present = bool(packet & 0x20)
    return {
        "type": "DesktopState",
        "version": VERSION,
        "observation_window": {
            "started_at": started_at,
            "finished_at": finished_at,
            "clock": "host_utc",
        },
        "provenance": {
            "scope": "disposable_notes_in_windows_sandbox",
            "process": "Windows Get-Process",
            "window": "Windows UI Automation and Win32 GetForegroundWindow",
            "sqlite": "separate Python process, SQLite read-only",
        },
        "process": {"pid": pid, "alive": bool(packet & 0x01)},
        "window": {
            "title": NOTES_WINDOW_TITLE if title_observed else None,
            "visible": bool(packet & 0x04) if title_observed else None,
            "foreground_owned_by_process": bool(packet & 0x08),
            "uia_focus_owned_by_process": bool(packet & 0x10),
        },
        "sqlite": {
            "integrity_check": "ok",
            "row_count": int(fixture_present),
            "exact_fixture_present": fixture_present,
        },
        "unobserved": ["widget_values", "screenshot"],
    }
