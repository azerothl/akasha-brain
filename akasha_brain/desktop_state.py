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


def notes_variables(state: dict) -> dict:
    if (state.get("type"), state.get("version")) != ("DesktopState", VERSION):
        raise ValueError("La prévision Notes exige un DesktopState v1.")
    return {
        "process.alive": state["process"]["alive"],
        **{f"window.{key}": value for key, value in state["window"].items()},
        **{f"sqlite.{key}": value for key, value in state["sqlite"].items()},
    }


def predict_notes_transition(before: dict, action: str) -> dict:
    """Projette l'état stabilisé de Notes dans le scénario synthétique."""
    expected = notes_variables(before)
    if not expected["process.alive"]:
        raise ValueError("Notes doit être en cours d'exécution.")
    if action == "save":
        if expected["sqlite.row_count"] != 0:
            raise ValueError("Le scénario d'enregistrement commence avec une base vide.")
        expected.update({"sqlite.row_count": 1, "sqlite.exact_fixture_present": True})
        expected["process.pid_relation"] = "same"
    elif action == "restart":
        expected.update({
            "process.pid_relation": "different",
            "window.title": NOTES_WINDOW_TITLE,
            "window.visible": True,
            "window.foreground_owned_by_process": True,
            "window.uia_focus_owned_by_process": True,
        })
    else:
        raise ValueError(f"Action Notes non prise en charge ({action}).")

    return {
        "type": "DesktopStatePrediction",
        "version": VERSION,
        "action": action,
        "from_observation_window": dict(before["observation_window"]),
        "from_pid": before["process"]["pid"],
        "expected": expected,
    }


def compare_notes_transition(prediction: dict, after: dict) -> dict:
    if (prediction.get("type"), prediction.get("version")) != ("DesktopStatePrediction", VERSION):
        raise ValueError("Prévision Notes v1 attendue.")
    observed = notes_variables(after)
    observed["process.pid_relation"] = "same" if after["process"]["pid"] == prediction["from_pid"] else "different"
    expected = prediction["expected"]
    if expected.keys() != observed.keys():
        raise ValueError("Variables Notes incohérentes entre prévision et observation.")
    variables = {name: {"predicted": value, "observed": observed[name]} for name, value in expected.items()}
    mismatches = [name for name, values in variables.items() if values["predicted"] != values["observed"]]
    return {
        "status": "failed" if mismatches else "passed",
        "matched": len(variables) - len(mismatches),
        "variables": variables,
        "mismatches": mismatches,
    }
