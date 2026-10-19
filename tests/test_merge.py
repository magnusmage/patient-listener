"""Profile merging (FR-11). The three worked examples from the workbook must pass."""

from __future__ import annotations

import unittest

from patient_listener.types import Need
from patient_listener.voice.merge import merge


class TestMerge(unittest.TestCase):
    def test_finding_plus_being_clear(self):
        # "mm at 5 s, hint offer at 7 s, turn ends at 20 s, what-I-heard, 15-min sessions."
        m = merge(frozenset({Need.FINDING_WORDS, Need.BEING_CLEAR}))
        self.assertEqual(m.backchannel_s, 5)
        self.assertEqual(m.offer_hint_s, 7)  # hints stay on: Being clear inherits
        self.assertEqual(m.max_wait_s, 20)
        self.assertEqual(m.max_session_min, 15)

    def test_finding_plus_getting_words_out(self):
        # "No mm, no hints, no take-your-time; ends at 20 s only if the text reads complete."
        m = merge(frozenset({Need.FINDING_WORDS, Need.WORDS_OUT}))
        self.assertIsNone(m.backchannel_s)  # NEVER wins
        self.assertIsNone(m.offer_hint_s)  # NEVER wins
        self.assertEqual(m.max_wait_s, 20)  # longest wait
        self.assertTrue(m.needs_complete_text)
        self.assertEqual(m.allowed_phrases, frozenset({"mm"}))  # take_your_time/no_rush banned out

    def test_being_heard_plus_saving_energy(self):
        # "mm at 5 s, no hints, 20 s wait, loudness, 10-minute sessions, rest every 5 turns."
        m = merge(frozenset({Need.BEING_HEARD, Need.SAVING_ENERGY}))
        self.assertEqual(m.backchannel_s, 5)
        self.assertIsNone(m.offer_hint_s)  # both INHERIT -> NEVER (no hint offers)
        self.assertEqual(m.max_wait_s, 20)  # max(12, 20)
        self.assertEqual(m.max_session_min, 10)  # smallest cap
        self.assertEqual(m.rest_every_turns, 5)
        self.assertEqual(m.max_turns, 15)

    def test_any_never_wins_for_backchannel(self):
        m = merge(frozenset({Need.FINDING_WORDS, Need.WORDS_OUT, Need.BEING_HEARD}))
        self.assertIsNone(m.backchannel_s)  # WORDS_OUT NEVER beats the numbers

    def test_smallest_limit_wins(self):
        m = merge(frozenset({Need.FINDING_WORDS, Need.SAVING_ENERGY}))
        self.assertEqual(m.max_session_min, 10)

    def test_banned_phrases_union(self):
        m = merge(frozenset({Need.WORDS_OUT, Need.BEING_HEARD, Need.SAVING_ENERGY}))
        for token in ("slow", "relax", "breathe", "calm", "shout", "one_more"):
            self.assertIn(token, m.banned_phrases)

    def test_default_is_finding_words(self):
        m = merge(frozenset())
        self.assertEqual(m.needs, frozenset({Need.FINDING_WORDS}))


if __name__ == "__main__":
    unittest.main()
