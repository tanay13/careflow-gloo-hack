#!/usr/bin/env python3
"""Reset the demo database to its deterministic synthetic starting state.

Usage: backend/.venv/bin/python scripts/seed_demo.py
(Equivalent to the "Reset demo data" button / POST /demo/reset.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import tools  # noqa: E402,F401
from db.seed import reset_and_seed  # noqa: E402

if __name__ == "__main__":
    reset_and_seed()
    print("Seeded synthetic demo data: 16 staff, 24 volunteers, 20 resources, calendars, 5 starting cases.")
    print("Next live case will be CF-1042 (submit the surgery-recovery scenario).")
