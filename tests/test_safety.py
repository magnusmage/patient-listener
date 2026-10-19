"""Safety phrase rules (FR-80/81/82/83, S-set). Safety recall must be 100%."""

from __future__ import annotations

import unittest

from patient_listener.voice.safety import SafetyKind, check, emergency_number


class TestStrokeSigns(unittest.TestCase):
    def test_four_phrasings(self):
        # S-01..S-04: four ways of describing stroke signs.
        phrases = [
            "my arm feels funny and words are worse today",
            "my face feels droopy",
            "my arm is weak",
            "I can't speak like yesterday",
        ]
        for p in phrases:
            sig = check(p)
            self.assertIsNotNone(sig, p)
            self.assertEqual(sig.kind, SafetyKind.STROKE, p)

    def test_emergency_numbers(self):
        self.assertEqual(emergency_number("UK"), "999")
        self.assertEqual(emergency_number("US"), "911")
        self.assertEqual(emergency_number("PK"), "1122")


class TestDistress(unittest.TestCase):
    def test_distress_phrases(self):
        for p in ["I'm useless", "what's the point", "no... point... me"]:
            sig = check(p)
            self.assertIsNotNone(sig, p)
            self.assertEqual(sig.kind, SafetyKind.DISTRESS, p)


class TestRedFlags(unittest.TestCase):
    def test_hoarse_pauses_loudness(self):
        sig = check("my voice has been hoarse for 3 weeks")
        self.assertEqual(sig.kind, SafetyKind.RED_FLAG_HOARSE)
        self.assertTrue(sig.pause_loudness)  # FR-82: loudness practice pauses

    def test_choking(self):
        self.assertEqual(check("I keep choking on water").kind, SafetyKind.RED_FLAG_CHOKING)

    def test_breathless(self):
        self.assertEqual(check("I get breathless").kind, SafetyKind.RED_FLAG_BREATHLESS)

    def test_sudden_hearing_loss(self):
        self.assertEqual(check("suddenly my hearing went").kind, SafetyKind.RED_FLAG_HEARING)

    def test_new_stammer(self):
        self.assertEqual(check("I have a new stammer").kind, SafetyKind.RED_FLAG_NEW_STAMMER)


class TestNoFalseAlarm(unittest.TestCase):
    def test_normal_practice_speech(self):
        for p in ["my grandson is Leo", "we went to Whitby", "I boil water in the kettle", ""]:
            self.assertIsNone(check(p), p)

    def test_stroke_takes_priority_over_distress(self):
        # If both appear, stroke (most time-critical) wins.
        sig = check("my arm is weak and I feel useless")
        self.assertEqual(sig.kind, SafetyKind.STROKE)


if __name__ == "__main__":
    unittest.main()
