"""Being heard loudness feedback (FR-13, N-09..N-13). Relative only, never an absolute dB."""

from __future__ import annotations

import unittest

from patient_listener.voice.loudness import baseline_db, loudness_feedback


class TestLoudness(unittest.TestCase):
    def test_baseline_is_median(self):
        self.assertEqual(baseline_db([-20, -24, -22, -26, -23]), -23)

    def test_below_baseline_prompts(self):
        # -3 dB below -> "a bit stronger?"
        self.assertEqual(loudness_feedback(-27.0, -24.0), "a_bit_stronger")

    def test_one_db_below_is_fine(self):
        # -1 dB is within tolerance (floor is -2 dB).
        self.assertIsNone(loudness_feedback(-25.0, -24.0))

    def test_at_or_above_baseline_fine(self):
        self.assertIsNone(loudness_feedback(-24.0, -24.0))
        self.assertIsNone(loudness_feedback(-20.0, -24.0))

    def test_feedback_is_a_key_not_a_number(self):
        # The return is a key the UI renders as a bar + words; no dB value leaks.
        result = loudness_feedback(-30.0, -24.0)
        self.assertEqual(result, "a_bit_stronger")
        self.assertNotIn("dB", str(result))


if __name__ == "__main__":
    unittest.main()
