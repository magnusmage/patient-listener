"""FSRS scheduling (D-13). The outcome->rating mapping is reproduced verbatim from the
workbook; the scheduler honours the due-word contract."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

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


class RealFsrsTests(unittest.TestCase):
    def test_matches_native_library_across_learning_and_review(self):
        from fsrs import Card as NativeCard, Scheduler as NativeScheduler, Rating as NativeRating
        scheduler = Scheduler(enable_fuzzing=False)
        native = NativeScheduler(desired_retention=.85, maximum_interval=60, enable_fuzzing=False)
        card = Card.new()
        expected = NativeCard.from_json(card.native.to_json())
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        for days, rating in ((0, Rating.AGAIN), (1, Rating.HARD), (4, Rating.GOOD), (20, Rating.EASY)):
            at = now + timedelta(days=days)
            card = scheduler.review_card(card, rating, at)
            expected, _ = native.review_card(expected, NativeRating(int(rating)), review_datetime=at)
            self.assertEqual(card.native.to_json(), expected.to_json())
            self.assertEqual(scheduler.retrievability(card, at),
                             native.get_card_retrievability(expected, current_datetime=at))

    def test_rating_boundary_and_unknown_timing(self):
        self.assertEqual(to_rating(Outcome.FOUND, HintLevel.NONE, 4), Rating.GOOD)
        self.assertEqual(to_rating(Outcome.FOUND, HintLevel.NONE, None), Rating.GOOD)
        self.assertEqual(to_rating(Outcome.UNSURE, HintLevel.NONE, 1), Rating.AGAIN)

    def test_timezone_and_workbook_limit(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        scheduler = Scheduler(enable_fuzzing=False)
        local = now.astimezone(timezone(timedelta(hours=5)))
        self.assertEqual(scheduler.review_card(Card.new(), Rating.EASY, local).due_dt(),
                         scheduler.review_card(Card.new(), Rating.EASY, now).due_dt())
        with self.assertRaises(ValueError):
            scheduler.review_card(Card.new(), Rating.EASY, now.replace(tzinfo=None))
        self.assertEqual(len(due_tonight({str(i): Card.new().to_json() for i in range(20)}, 99)), 10)
        self.assertEqual(due_tonight({'new': Card.new().to_json()}, 0), [])

    def test_least_retrievable_due_word_first(self):
        scheduler = Scheduler(enable_fuzzing=False)
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        older = scheduler.review_card(Card.new(), Rating.EASY, now - timedelta(days=50))
        newer = scheduler.review_card(Card.new(), Rating.EASY, now - timedelta(days=20))
        self.assertEqual(due_tonight({'newer': newer.to_json(), 'older': older.to_json()}, now=now),
                         ['older', 'newer'])


class StoredScheduleTests(unittest.TestCase):
    def make_store(self, path=':memory:'):
        from patient_listener.store.sqlite_store import SqliteStore
        store = SqliteStore(path)
        self.addCleanup(store.close)
        store._scheduler = Scheduler(enable_fuzzing=False)
        store.add_person('p', 'Person', frozenset())
        for wid in ('one', 'two'):
            store.add_word_draft(wid, 'p', wid, 'object')
            store.approve_word(wid, 'slt')
        return store

    def attempt(self, at, word='one'):
        from patient_listener.schemas import Attempt
        return Attempt('session', word, HintLevel.NONE, Outcome.FOUND, 2, 1, True, at)

    def test_attempt_updates_card_and_nightly_selects_other_due_word(self):
        from patient_listener.plan_generation import select_words
        from patient_listener.llm.plan import build_plan
        store = self.make_store()
        at = datetime.now(timezone.utc)
        store.log_attempt(self.attempt(at))
        card = Card.from_json(store.get_card('p', 'one'))
        self.assertEqual(card.native.last_review, at)
        self.assertGreater(card.due_dt(), at)
        words, _ = select_words(store, 'p', 10)
        self.assertEqual([w.id for w in words], ['two'])
        store.set_card('p', 'obsolete', Card.new().to_json())
        self.assertEqual([i.word_id for i in build_plan(store, 'p', k=1).items], ['two'])

    def test_attempt_and_card_are_atomic(self):
        store = self.make_store()
        with patch.object(store, '_write_card', side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):
                store.log_attempt(self.attempt(datetime.now(timezone.utc)))
        self.assertEqual(store.attempts_for('p'), [])
        self.assertIsNone(store.get_card('p', 'one'))
        store.log_attempt(self.attempt(datetime.now(timezone.utc)))
        self.assertEqual(len(store.attempts_for('p')), 1)

    def test_restart_preserves_native_card_and_history(self):
        from patient_listener.store.sqlite_store import SqliteStore
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.db')
            store = self.make_store(path)
            store.log_attempt(self.attempt(datetime.now(timezone.utc)))
            saved = store.get_card('p', 'one')
            store.close()
            reopened = SqliteStore(path)
            try:
                self.assertEqual(reopened.get_card('p', 'one'), saved)
                self.assertEqual(len(reopened.attempts_for('p')), 1)
            finally:
                reopened.close()

    def test_prototype_cards_replay_history_and_retain_original(self):
        from patient_listener.store.sqlite_store import SqliteStore
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.db')
            store = self.make_store(path)
            at = datetime(2026, 10, 7, tzinfo=timezone.utc)
            store.log_attempt(self.attempt(at))
            expected_stability = Card.from_json(store.get_card('p', 'one')).native.stability
            legacy = {'stability': 99, 'difficulty': 5, 'reps': 7, 'due': '', 'last_review': ''}
            store.set_card('p', 'one', json.dumps(legacy))
            store.set_card('p', 'two', json.dumps(legacy))
            store.close()
            reopened = SqliteStore(path)
            try:
                migrated = Card.from_json(reopened.get_card('p', 'one'))
                self.assertEqual(migrated.legacy, legacy)
                self.assertEqual(migrated.native.stability, expected_stability)
                self.assertEqual(migrated.native.last_review, at)
                self.assertIsNone(Card.from_json(reopened.get_card('p', 'two')).native.last_review)
                self.assertEqual(len(reopened.attempts_for('p')), 1)
            finally:
                reopened.close()

    def test_missing_card_is_rebuilt_from_saved_attempts(self):
        store = self.make_store()
        at = datetime.now(timezone.utc)
        store.log_attempt(self.attempt(at))
        store._db.execute('DELETE FROM cards')
        store._db.commit()
        store._initialize_schedule()
        self.assertEqual(Card.from_json(store.get_card('p', 'one')).native.last_review, at)

    def test_backdated_attempt_replays_in_time_order(self):
        store = self.make_store()
        at = datetime(2026, 10, 7, tzinfo=timezone.utc)
        store.log_attempt(self.attempt(at + timedelta(days=2)))
        store.log_attempt(self.attempt(at))
        card = Card.from_json(store.get_card('p', 'one'))
        expected = store._scheduler.review_card(Card.new(), Rating.EASY, at)
        expected = store._scheduler.review_card(expected, Rating.EASY, at + timedelta(days=2))
        self.assertEqual(card.native.stability, expected.native.stability)
        self.assertEqual(card.due_dt(), expected.due_dt())
        self.assertEqual(len(store.attempts_for('p')), 2)

    def test_factory_passes_fsrs_configuration(self):
        from patient_listener.config import Settings
        from patient_listener.store.factory import open_store
        store = open_store(Settings(database_url='sqlite:///:memory:',
                                   fsrs_desired_retention=.93, fsrs_maximum_interval=12))
        try:
            self.assertEqual(store._scheduler.native.desired_retention, .93)
            self.assertEqual(store._scheduler.native.maximum_interval, 12)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
