"""FSRS scheduling (D-13). The outcome->rating mapping is reproduced verbatim from the
workbook; the scheduler honours the due-word contract."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from patient_listener.schedule.fsrs import Card, Rating, Scheduler, due_tonight, to_rating
from patient_listener.types import HintLevel, Outcome


class TestRatingMapping(unittest.TestCase):
    def test_no_hint_fast_is_easy(self):
        self.assertEqual(to_rating(Outcome.FOUND, HintLevel.NONE, 3.0), Rating.EASY)

    def test_no_hint_slow_is_good(self):
        self.assertEqual(to_rating(Outcome.FOUND, HintLevel.NONE, 6.0), Rating.GOOD)

    def test_after_meaning_or_sound_is_hard(self):
        self.assertEqual(to_rating(Outcome.FOUND, HintLevel.MEANING, 2.0), Rating.HARD)
        self.assertEqual(to_rating(Outcome.FOUND, HintLevel.SOUND, 2.0), Rating.HARD)

    def test_repeated_or_moved_on_is_again(self):
        self.assertEqual(to_rating(Outcome.REPEATED, HintLevel.WORD, 1.0), Rating.AGAIN)
        self.assertEqual(to_rating(Outcome.MOVED_ON, HintLevel.NONE, 20.0), Rating.AGAIN)


class TestScheduler(unittest.TestCase):
    def test_better_recall_longer_interval(self):
        sched = Scheduler(desired_retention=0.85, maximum_interval=60)
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        card = Card.new()
        easy = sched.review_card(card, Rating.EASY, now)
        again = sched.review_card(card, Rating.AGAIN, now)
        self.assertGreater(easy.due_dt(), again.due_dt())

    def test_due_tonight_caps_at_k(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        # 15 brand-new cards (all due now).
        cards = {f"w{i}": Card.new().to_json() for i in range(15)}
        due = due_tonight(cards, k=10, now=now)
        self.assertEqual(len(due), 10)

    def test_due_tonight_excludes_future(self):
        sched = Scheduler()
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        reviewed = sched.review_card(Card.new(), Rating.EASY, now)  # due in the future
        cards = {"future": reviewed.to_json(), "new": Card.new().to_json()}
        due = due_tonight(cards, k=10, now=now)
        self.assertIn("new", due)
        self.assertNotIn("future", due)


if __name__ == "__main__":
    unittest.main()
