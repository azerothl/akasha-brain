"""Rend `notes_store` importable depuis `tests/` (banc, sans paquet installé)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
