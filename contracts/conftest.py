"""Rend le paquet `akasha_contracts` importable depuis `tests/` (sans install)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
