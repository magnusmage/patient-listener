"""Word matcher (FR-22, DR-4, W-set). Precision over recall: a sound-alike is confirmed,
never logged on its own."""

from __future__ import annotations

import unittest

from patient_listener.voice.matcher import (
    CONFIRM_THRESHOLD,
    FOUND_THRESHOLD,
    best_match,
    score,
)

from support import word


class TestMatcherScore(unittest.TestCase):
    def test_dr4_bands(self):
        # Worked values from the workbook DR-4 run.
        self.assertGreaterEqual(score("kettle", "kettle"), FOUND_THRESHOLD)  # 1.00 -> log
        for heard in ("lee oh", "bisket", "Leah"):
            target = {"lee oh": "Leo", "bisket": "Biscuit", "Leah": "Leo"}[heard]
            s = score(heard, target)
            self.assertTrue(
                CONFIRM_THRESHOLD <= s < FOUND_THRESHOLD, f"{heard}->{target} = {s}"
            )  # confirm band
        self.assertLess(score("teapot", "kettle"), CONFIRM_THRESHOLD)  # 0.33 -> not a match

    def test_exact_values(self):
        self.assertAlmostEqual(score("lee oh", "Leo"), 0.85, places=2)
        self.assertAlmostEqual(score("teapot", "kettle"), 0.333, places=2)


class TestBestMatch(unittest.TestCase):
    def setUp(self):
        self.words = [
            word("w-leo", "Leo", first_sound="L"),
            word("w-biscuit", "Biscuit", "person", "Leo's puppy", "B"),
            word("w-kettle", "kettle", "object", "boil water", "K"),
            word("w-whitby", "Whitby", "place", "seaside town", "W"),
        ]

    def test_found_exact(self):
        m = best_match(["kettle"], self.words)
        self.assertIsNotNone(m)
        self.assertEqual(m.word.id, "w-kettle")
        self.assertTrue(m.is_found)

    def test_found_in_phrase(self):
        # "my grandson is Leo" matches on the token Leo.
        m = best_match(["my", "grandson", "is", "Leo"], self.words)
        self.assertEqual(m.word.id, "w-leo")
        self.assertTrue(m.is_found)

    def test_partial_then_full(self):
        # "Whit... Whitby!" -> matches Whitby; repeated-word collapse doesn't break it.
        m = best_match(["Whit", "Whitby"], self.words)
        self.assertEqual(m.word.id, "w-whitby")

    def test_confirm_band(self):
        m = best_match(["Leah"], self.words)
        self.assertEqual(m.word.id, "w-leo")
        self.assertTrue(m.needs_confirm)

    def test_different_word_no_match(self):
        self.assertIsNone(best_match(["teapot"], self.words))

    def test_empty_word_list(self):
        self.assertIsNone(best_match(["Leo"], []))


if __name__ == "__main__":
    unittest.main()
