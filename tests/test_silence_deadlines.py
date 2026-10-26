"""FR-03 controller deadlines and real adapter fake-clock tests; no GPU/network."""
import asyncio
from dataclasses import replace
import unittest

from patient_listener.app.session import AppSession
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.types import Need, State
from patient_listener.voice.controller import PatienceController
from patient_listener.voice.merge import merge


class ControllerDeadlineTests(unittest.TestCase):
    def controller(self, needs=frozenset({Need.FINDING_WORDS})):
        c = PatienceController(merge(needs))
        c.target = object()  # Timing eligibility requires a target, never its contents.
        c.on_silence(10.125)
        return c

    def test_absolute_deadlines_do_not_drift(self):
        c = self.controller()
        self.assertEqual(c.next_silence_deadline(10.125), 14.125)
        c.on_silence(14.205)
        self.assertEqual(c.next_silence_deadline(14.205), 17.125)
        c.on_silence(17.205)
        self.assertEqual(c.next_silence_deadline(17.205), 30.125)

    def test_speech_invalidates_old_silence(self):
        c = self.controller()
        c.on_speech(14.12)
        self.assertIsNone(c.next_silence_deadline(14.125))
        c.on_silence(15)
        self.assertEqual(c.next_silence_deadline(15), 19)

    def test_disabled_waits_and_exhausted_backchannels_do_not_spin(self):
        c = self.controller()
        c.cfg = replace(c.cfg, backchannel_s=None, offer_hint_s=None, max_wait_s=None)
        self.assertIsNone(c.next_silence_deadline(20))
        c.cfg = replace(c.cfg, backchannel_s=4)
        c.backchannels = c.cfg.max_backchannels_per_turn
        self.assertIsNone(c.next_silence_deadline(20))

    def test_words_out_schedules_only_completeness_and_never_spins_while_pending(self):
        c = self.controller(frozenset({Need.WORDS_OUT}))
        self.assertEqual(c.next_silence_deadline(10.125), 18.125)
        c.on_silence(18.125)
        self.assertIsNone(c.next_silence_deadline(18.125))
        c.on_complete(False, 19)
        self.assertEqual(c.next_silence_deadline(19), 27)

    def test_no_hint_without_target_and_no_events_after_terminal_state(self):
        c = self.controller()
        c.target = None
        c.on_silence(14.125)
        self.assertEqual(c.next_silence_deadline(15), 30.125)
        for state in (State.ENDED, State.SAFETY_STOP, State.SPEAKING, State.PRAISING):
            c.state = state
            self.assertIsNone(c.next_silence_deadline(40))

    def test_merged_words_out_profile_has_no_backchannel_or_hint_deadline(self):
        c = self.controller(frozenset({Need.WORDS_OUT, Need.FINDING_WORDS}))
        self.assertEqual(c.next_silence_deadline(10.125), 30.125)


class AdapterDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = SqliteStore(check_same_thread=False)
        self.people = seed_all(self.store)
        self.clock = 0.0
        self.events = []
        self.sessions = []

    async def asyncTearDown(self):
        tasks = []
        for s in self.sessions:
            tasks.extend(t for t in (s._ticker, s._advance, s._cap) if t is not None)
            s.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.store.close()

    async def session(self, person='margaret'):
        async def send(event):
            self.events.append((self.clock, event['type']))
        s = AppSession(self.store, self.people[person], send)
        self.sessions.append(s)
        s.now = lambda: self.clock
        s._schedule_advance = lambda delay: None
        await s.next_prompt()
        self.events.clear()
        return s

    async def test_finding_words_adapter_fires_at_4_7_20_without_polling(self):
        for overshoot in (0.0, 0.08):
            s = await self.session()
            self.clock = 0.0
            self.events.clear()
            sleeps = []
            async def sleep(delay):
                sleeps.append(delay)
                self.clock += delay + overshoot
            s._sleep = sleep
            await s._tick()
            timed = [(t, kind) for t, kind in self.events
                     if kind in ('backchannel', 'offerHint', 'moveOn')]
            self.assertEqual([kind for _, kind in timed], ['backchannel', 'offerHint', 'moveOn'])
            for (actual, _), expected in zip(timed, (4, 7, 20)):
                self.assertAlmostEqual(actual, expected + overshoot)
            self.assertEqual(len(sleeps), 3)

    async def test_speech_cancels_sleep_without_a_late_backchannel(self):
        s = await self.session()
        entered = asyncio.Event()
        async def sleep(delay):
            entered.set()
            await asyncio.Event().wait()
        s._sleep = sleep
        await s._pause()
        task = s._ticker
        await asyncio.wait_for(entered.wait(), 1)
        await s.on_audio_speech()
        await asyncio.wait_for(task, 1)
        self.assertIsNone(s.engine.controller.silence_started)
        self.assertFalse(any(kind in ('backchannel', 'offerHint', 'moveOn')
                             for _, kind in self.events))

    async def test_words_out_rechecks_at_eight_seconds_without_polling_or_audio(self):
        s = await self.session('daniyal')
        wakes = []
        async def sleep(delay):
            self.clock += delay
            wakes.append(self.clock)
            if len(wakes) == 2:
                s.ended = True
        s._sleep = sleep
        await s._tick()
        self.assertEqual(wakes, [8, 16])
        self.assertFalse(any(kind in ('backchannel', 'offerHint', 'reply', 'moveOn')
                             for _, kind in self.events))

    async def test_switching_waits_off_before_deadline_prevents_output(self):
        s = await self.session()
        async def sleep(delay):
            self.clock += delay
            cfg = replace(s.cfg, backchannel_s=None, offer_hint_s=None, max_wait_s=None)
            s.cfg = s.engine.cfg = s.engine.controller.cfg = cfg
        s._sleep = sleep
        await s._tick()
        self.assertFalse(any(kind in ('backchannel', 'offerHint', 'moveOn')
                             for _, kind in self.events))
