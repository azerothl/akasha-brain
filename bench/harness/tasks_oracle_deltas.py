"""Transport borné des écarts du contrôle Tâches par le code de sortie invité."""

from collections import Counter

FILTERS = ("À faire", "Terminées", "Toutes")
PACKET = 0x60000000
COUNT_LIMIT = 15


def encode_oracle(expected: dict, observed: dict, sqlite_unchanged: bool) -> int:
    code = PACKET | (int(sqlite_unchanged) << 27)
    for index, name in enumerate(FILTERS):
        wanted, shown = expected[name], observed[name]
        wanted_counts, shown_counts = Counter(wanted), Counter(shown)
        missing = (wanted_counts - shown_counts).total()
        unexpected = (shown_counts - wanted_counts).total()
        wrong_order = not (missing or unexpected) and wanted != shown
        delta = min(missing, COUNT_LIMIT) | (min(unexpected, COUNT_LIMIT) << 4) | (int(wrong_order) << 8)
        code |= delta << (index * 9)
    return code


def decode_oracle(code: int) -> dict:
    if code & ~0x0FFFFFFF != PACKET:
        raise RuntimeError(f"Contrôle Tâches interrompu (code invité {code}).")
    deltas = {}
    for index, name in enumerate(FILTERS):
        part = (code >> (index * 9)) & 0x1FF
        deltas[name] = {
            "missing": part & 0xF,
            "unexpected": (part >> 4) & 0xF,
            "wrong_order": bool(part & 0x100),
        }
    return {
        "filters": {name: not any(delta.values()) for name, delta in deltas.items()},
        "filter_deltas": deltas,
        "sqlite_unchanged": bool(code & 0x08000000),
        "guest_exit_code": code,
    }
