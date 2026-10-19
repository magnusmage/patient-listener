#!/usr/bin/env python3
"""Run the full test suite and the release gate with no third-party dependencies.

    python run_tests.py

Equivalent to ``PYTHONPATH=src python -m unittest discover -s tests``. On a dev box with the
dev group installed, ``pytest`` also works (see pyproject.toml).
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(ROOT, "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    # Print the release gate values (the seven conditions that decide a ship).
    try:
        import test_release_gate as g

        print("\n== Release gate ==")
        checks = [
            ("P.interruptions_le_15s", g.gate_p_interruptions(), lambda v: v == 0),
            ("W.precision", round(g.gate_w_precision(), 3), lambda v: v >= 0.95),
            ("S.recall", round(g.gate_s_recall(), 3), lambda v: v == 1.0),
            ("F.fallback_within_2s", round(g.gate_fallback_coverage(), 3), lambda v: v == 1.0),
            ("reveal_reached_person", g.gate_reveal_reached_person(), lambda v: v == 0),
            ("N.words_out_spoke_in_block", g.gate_words_out_spoke_in_block(), lambda v: v == 0),
            ("N.clear_unconfirmed_found", g.gate_clear_unconfirmed_found(), lambda v: v == 0),
        ]
        green = all(ok(v) for _, v, ok in checks)
        for name, v, ok in checks:
            print(f"  {'GREEN' if ok(v) else 'RED  '}  {name:30} = {v}")
        print("RELEASE GATE:", "GREEN" if green else "RED")
    except Exception as exc:  # pragma: no cover
        print("gate summary skipped:", exc)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
