"""FR-14: Being clear success requires the check tap, not a spoken yes."""
import asyncio
import unittest

from patient_listener.app import bridge
from patient_listener.app.session import AppSession
from patient_listener.llm.reply import TemplateLlm
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_margaret
from patient_listener.types import Need, State
from patient_listener.voice.merge import merge
from patient_listener.voice.session import SessionEngine


class ConfirmationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore()
        self.pid = seed_margaret(self.store)
        self.addCleanup(self.store.close)
        self.words = self.store.words(self.pid)
        self.kettle = next(w for w in self.words if w.text == 'kettle')

    def engine(self, needs):
        eng = SessionEngine(merge(frozenset(needs)), self.store, TemplateLlm(),
                            person_id=self.pid, words=self.words)
        eng.feed(('prompt', self.kettle, 'photo', 0.0))
        return eng

    def test_yes_cannot_confirm_clear_or_combined_profiles(self):
        for needs in ({Need.BEING_CLEAR}, {Need.BEING_CLEAR, Need.SAVING_ENERGY}):
            with self.subTest(needs=needs):
                eng = self.engine(needs)
                eng.feed(('heard', 'kettle', 1.0))
                eng.feed(('yes', 2.0))
                self.assertEqual(self.store.attempts_for(self.pid), [])
                self.assertEqual(eng.found, set())
                self.assertEqual(eng.replies, [])
                self.assertEqual(eng.controller.state, State.CONFIRMING)
                self.assertEqual(eng.controller.pending.word.id, self.kettle.id)

    def test_check_tap_logs_once_after_ignored_yes(self):
        eng = self.engine({Need.BEING_CLEAR})
        eng.feed(('heard', 'kettle', 1.0))
        eng.feed(('yes', 2.0))
        self.assertEqual(self.store.attempts_for(self.pid), [])
        eng.feed(('confirm_tap', True, 3.0))
        eng.feed(('confirm_tap', True, 4.0))
        rows = self.store.attempts_for(self.pid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['word_id'], self.kettle.id)
        self.assertEqual(rows[0]['outcome'], 'found')
        self.assertEqual(eng.found, {'kettle'})

    def test_rejecting_tap_clears_pending_and_stale_check_does_nothing(self):
        eng = self.engine({Need.BEING_CLEAR})
        eng.feed(('heard', 'kettle', 1.0))
        eng.feed(('confirm_tap', False, 2.0))
        eng.feed(('confirm_tap', True, 3.0))
        self.assertEqual(self.store.attempts_for(self.pid), [])
        self.assertIsNone(eng.controller.pending)

    def test_finding_words_soundalike_still_accepts_yes(self):
        eng = self.engine({Need.FINDING_WORDS})
        eng.feed(('heard', 'kentle', 1.0))
        self.assertEqual(eng.controller.state, State.CONFIRMING)
        eng.feed(('yes', 2.0))
        self.assertEqual(len(self.store.attempts_for(self.pid)), 1)

    def test_clear_hint_offer_still_accepts_yes(self):
        eng = self.engine({Need.BEING_CLEAR, Need.FINDING_WORDS})
        eng.feed(('silence', 0.0))
        eng.feed(('silence', 7.0))
        self.assertEqual(eng.controller.state, State.HINT_OFFERED)
        eng.feed(('yes', 8.0))
        self.assertEqual(eng.controller.state, State.HINTING)
        self.assertEqual(self.store.attempts_for(self.pid), [])

    def test_confirmation_payload_requires_actual_boolean(self):
        for value in ('false', 'true', 1, 0, None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.client_message_to_event({'type': 'confirm_tap', 'ok': value})
        self.assertEqual(bridge.client_message_to_event({'type':'confirm_tap','ok':False}),
                         ('confirm_tap', {'ok':False}))


class AppConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_success_or_advance_until_tap_through_app_controls(self):
        store = SqliteStore(check_same_thread=False)
        pid = seed_margaret(store)
        store.add_person(pid, 'Margaret', frozenset({Need.BEING_CLEAR}))
        events = []
        async def send(event): events.append(event)
        s = AppSession(store, pid, send)
        try:
            await s.start()
            await s.on_audio_final(s.current.text)
            self.assertTrue(any(e['type'] == 'whatIHeard' for e in events))
            events.clear()
            await s.handle({'type': 'yes'})
            self.assertEqual(store.attempts_for(pid), [])
            self.assertIsNone(s._advance)
            self.assertFalse(any(e['type'] in ('found', 'reply', 'attempt') for e in events))
            await s.handle({'type': 'confirm_tap', 'ok': True})
            self.assertEqual(len(store.attempts_for(pid)), 1)
            self.assertTrue(any(e['type'] == 'found' for e in events))
            self.assertIsNotNone(s._advance)
        finally:
            tasks = [t for t in (s._ticker, s._advance) if t is not None]
            s.close()
            await asyncio.gather(*tasks, return_exceptions=True)
            store.close()
