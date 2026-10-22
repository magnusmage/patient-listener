"""Full answers, duration caps, and database AI policy. No GPU/paid requests."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from patient_listener.app.deps import build_state
from patient_listener.app.session import AppSession
from patient_listener.config import Settings
from patient_listener.llm.factory import build_llm
from patient_listener.llm.reply import TemplateLlm, produce_reply
from patient_listener.nightly import run_for_person
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.types import Need, State
from patient_listener.voice.merge import merge
from patient_listener.voice.session import SessionEngine
from test_faults import _facts


class TurnTextTests(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore(ai_enabled=True)
        self.addCleanup(self.store.close)
        self.llm = TemplateLlm()
        self.llm.is_complete = AsyncMock(return_value=False)
        self.e = SessionEngine(merge(frozenset({Need.WORDS_OUT})), self.store, self.llm)
        self.e.feed(('prompt', None, 'day', 0.0))

    def test_completion_gets_whole_answer_across_segments(self):
        self.e.feed(('heard', 'I went to', 1.0))
        self.e.feed(('speech', 2.0))
        self.e.feed(('heard', 'the park', 3.0))
        self.e.feed(('silence', 4.0))
        self.e.feed(('silence', 12.0))
        self.llm.is_complete.assert_awaited_once_with('day', 'I went to the park', timeout_s=1.0)
        self.assertEqual(self.e.last_heard, 'the park')
        self.assertEqual(self.e._reply_facts().last_words_heard, 'I went to the park')

    def test_new_prompt_and_stop_clear_previous_answer(self):
        self.e.feed(('heard', 'private previous answer', 1.0))
        self.e.feed(('prompt', None, 'new question', 2.0))
        self.assertEqual((self.e.turn_text, self.e.last_heard), ('', ''))
        self.e.feed(('heard', 'new answer', 3.0))
        self.e.feed(('stop', 4.0))
        self.assertEqual((self.e.turn_text, self.e.last_heard), ('', ''))
        self.e.feed(('heard', 'late answer', 5.0))
        self.assertEqual(self.e.turn_text, '')

    def test_typed_edit_replaces_answer_and_full_words_out_is_not_truncated(self):
        self.e.feed(('heard', 'old answer', 1.0))
        text = ' '.join(f'word{i}' for i in range(25))
        self.e.feed(('typed', text, 2.0))
        self.assertEqual(self.e._reply_facts().last_words_heard, text)
        self.e.cfg = merge(frozenset({Need.FINDING_WORDS}))
        self.assertEqual(len(self.e._reply_facts().last_words_heard.split()), 20)

    def test_safety_clears_transient_turn_text(self):
        self.e.feed(('heard', 'my arm is weak', 1.0))
        self.assertEqual((self.e.turn_text, self.e.last_heard), ('', ''))

    def test_disabled_ai_keeps_waiting_until_done(self):
        self.store.set_ai_enabled(False)
        self.llm.reply = AsyncMock(return_value='Tell me more.')
        self.e.feed(('heard', 'I went to the park', 1.0))
        self.e.feed(('silence', 2.0))
        self.e.feed(('silence', 10.0))
        self.llm.is_complete.assert_not_awaited()
        self.assertEqual(self.e.replies, [])
        self.e.feed(('done', 11.0))
        self.llm.reply.assert_not_awaited()
        self.assertTrue(self.e.replies)  # fixed template, not a model response

    def test_safety_phrase_split_across_final_segments_stops_turn(self):
        self.e.feed(('heard', 'my arm', 1.0))
        self.e.feed(('heard', 'is weak', 2.0))
        self.assertEqual(self.e.controller.state, State.SAFETY_STOP)
        self.assertEqual(self.e.turn_text, '')


class InitialPolicyTests(unittest.TestCase):
    def test_env_initial_value_is_used_once_and_restart_preserves_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.db')
            state = build_state(path, Settings(ai_enabled=False, console_demo_enabled=False))
            self.assertFalse(state.store.is_ai_enabled())
            state.store.set_ai_enabled(True)
            state.store.close()
            state = build_state(path, Settings(ai_enabled=False, console_demo_enabled=False))
            try: self.assertTrue(state.store.is_ai_enabled())
            finally: state.store.close()

    def test_nightly_checks_switch_for_each_word_and_discards_disabled_result(self):
        s = SqliteStore(ai_enabled=True)
        try:
            pid = seed_all(s)['margaret']
            llm = TemplateLlm()
            async def turn_off(facts):
                s.set_ai_enabled(False)
                return 'A bright invented meaning.'
            llm.plan = AsyncMock(side_effect=turn_off)
            run_for_person(s, pid, llm)
            self.assertEqual(llm.plan.await_count, 1)
            self.assertTrue(all(w.hints.meaning != 'A bright invented meaning.' for w in s.words(pid)))
            llm.plan.reset_mock()
            run_for_person(s, pid, llm)
            llm.plan.assert_not_awaited()
        finally: s.close()


class LivePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_on_off_changes_existing_factory_model_without_reconnect(self):
        s = SqliteStore(ai_enabled=False)
        try:
            model = TemplateLlm()
            model.reply = AsyncMock(return_value='Tell me more.')
            model.plan = AsyncMock(return_value='A safe meaning.')
            model.is_complete = AsyncMock(return_value=True)
            with patch.dict('sys.modules', {'openai': object()}), patch(
                'patient_listener.llm.factory.TokenFactoryLlm', return_value=model
            ):
                llm = build_llm(Settings(nebius_api_key='test-only', ai_enabled=False), s)
            self.assertIsNone(await llm.reply(_facts(), .2))
            self.assertIsNone(await llm.plan(None))
            self.assertFalse(await llm.is_complete('Q', 'A', .2))
            model.reply.assert_not_awaited(); model.plan.assert_not_awaited()
            model.is_complete.assert_not_awaited()
            s.set_ai_enabled(True)
            self.assertEqual(await llm.reply(_facts(), .2), 'Tell me more.')
            self.assertEqual(await llm.plan(None), 'A safe meaning.')
            self.assertTrue(await llm.is_complete('Q', 'A', .2))
            s.set_ai_enabled(False)
            self.assertIsNone(await llm.reply(_facts(), .2))
            self.assertEqual(model.reply.await_count, 1)
        finally: s.close()

    async def test_switch_off_during_reply_prevents_retry_and_discards_line(self):
        s = SqliteStore(ai_enabled=True)
        try:
            model = TemplateLlm()
            async def reply(facts, timeout):
                s.set_ai_enabled(False)
                return 'Is that Biscuit?'
            model.reply = AsyncMock(side_effect=reply)
            result = await produce_reply(model, _facts(), ai_enabled=s.is_ai_enabled)
            self.assertTrue(result.used_template)
            self.assertEqual(result.reason, 'ai_disabled')
            self.assertEqual(model.reply.await_count, 1)
        finally: s.close()

    async def test_retry_gets_reason_and_remaining_budget(self):
        model = TemplateLlm()
        received = []
        async def reply(facts, timeout):
            received.append((facts.rejection_reason, timeout))
            if len(received) == 1:
                await asyncio.sleep(.03)
                return 'Is that Biscuit?'
            return 'Tell me more.'
        model.reply = reply
        result = await produce_reply(model, _facts(), timeout_s=5)
        self.assertFalse(result.used_template)
        self.assertEqual(received[0][0], '')
        self.assertEqual(received[1][0], 'reveals_word')
        self.assertLess(received[1][1], received[0][1])

    async def test_retry_cannot_extend_total_timeout(self):
        model = TemplateLlm()
        async def reply(facts, timeout):
            if not facts.rejection_reason: return 'Is that Biscuit?'
            await asyncio.sleep(10)
        model.reply = reply
        result = await asyncio.wait_for(produce_reply(model, _facts(), timeout_s=.03), 5)
        self.assertTrue(result.used_template)
        self.assertEqual(result.reason, 'reveals_word->timeout')


class SessionCapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = SqliteStore(check_same_thread=False, ai_enabled=False)
        self.pid = seed_all(self.store)['margaret']
        self.events = []
        self.audio = False
        async def send(event):
            self.events.append(event)
            if self.audio and event.get('replace_audio'): self.s.set_audio_busy(True)
        self.s = AppSession(self.store, self.pid, send)
        self.s.cfg = replace(self.s.cfg, max_session_min=3)
        await self.s.start()
        self.time = 0.0
        self.s.now = lambda: self.time
        self.events.clear()

    async def asyncTearDown(self):
        tasks = [t for t in (self.s._cap, self.s._ticker, self.s._advance) if t is not None]
        self.s.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.store.close()

    async def expire(self):
        self.time = 180.0
        self.s._arm_cap()
        task = self.s._cap
        await asyncio.wait_for(task, 10)

    async def test_timer_ends_with_closing_line_and_late_events_do_nothing(self):
        await self.expire()
        self.assertEqual([e['type'] for e in self.events], ['reply', 'ended'])
        self.assertEqual(self.events[0]['text'], 'Well done today.')
        self.assertEqual(self.events[1]['reason'], 'session_cap')
        count = len(self.events)
        await self.s.handle({'type':'help'})
        await self.s.on_audio_final('Biscuit')
        self.assertEqual(len(self.events), count)
        self.assertTrue(self.s.ended)
        self.assertIsNone(self.s._cap)

    async def test_extension_and_no_limit_do_not_allow_shortening_or_restart_reset(self):
        started = self.s._t0
        await self.s.start()
        self.assertEqual(self.s._t0, started)
        self.assertEqual(self.events, [])
        await self.s.handle({'type':'extend_session','minutes':6})
        self.assertEqual(self.s._session_limit, 6)
        for value in (3, 2, True, '10', 121):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.s.handle({'type':'extend_session','minutes':value})
        await self.s.handle({'type':'extend_session','minutes':None})
        self.assertIsNone(self.s._cap)
        self.time = 100000
        await self.s._watch_cap()
        self.assertFalse(self.s.ended)
        with self.assertRaises(ValueError): self.s.extend_session(20)

    async def test_cap_still_applies_during_rest(self):
        await self.s.handle({'type':'rest'})
        self.events.clear()
        await self.expire()
        self.assertTrue(self.s.ended)

    async def test_closing_waits_for_playback_and_stop_interrupts_it(self):
        self.audio = True
        self.time = 180
        self.s._arm_cap()
        task = self.s._cap
        for _ in range(100):
            if self.s.closing: break
            await asyncio.sleep(.01)
        self.assertTrue(self.s.closing)
        self.assertFalse(self.s.ended)
        self.assertFalse(any(e['type']=='ended' for e in self.events))
        await self.s.handle({'type':'stop'})
        await asyncio.wait_for(task, 10)
        self.assertTrue(self.s.ended)
        self.assertEqual(sum(e['type']=='ended' for e in self.events), 1)

    async def test_no_limit_from_start_has_no_expiry_task(self):
        old_cap = self.s._cap
        self.s.close()
        await asyncio.gather(old_cap, return_exceptions=True)
        async def send(event): self.events.append(event)
        self.s = AppSession(self.store, self.pid, send)
        self.s.cfg = replace(self.s.cfg, max_session_min=None)
        await self.s.start()
        self.events.clear()
        self.s.now = lambda: 1000000
        await self.s._watch_cap()
        self.assertIsNone(self.s._cap)
        self.assertFalse(self.s.ended)
        self.assertEqual(self.events, [])

    async def test_closing_finishes_after_playback_ack(self):
        self.audio = True
        self.time = 180
        self.s._arm_cap()
        task = self.s._cap
        for _ in range(100):
            if self.s.closing: break
            await asyncio.sleep(.01)
        self.s.set_audio_busy(False)
        await asyncio.wait_for(task, 10)
        self.assertTrue(self.s.ended)
        self.assertEqual(self.events[-1]['reason'], 'session_cap')

    async def test_stop_and_safety_cancel_duration_task(self):
        cap = self.s._cap
        await self.s.on_audio_partial('my arm is weak')
        await asyncio.gather(cap, return_exceptions=True)
        self.assertTrue(self.s.ended)
        self.assertIsNone(self.s._cap)

    async def test_partial_text_is_not_duplicated_and_split_safety_cancels_cap(self):
        await self.s.on_audio_final('my arm')
        await self.s.on_audio_partial('is')
        self.assertEqual(self.s.engine.turn_text, 'my arm')
        cap = self.s._cap
        await self.s.on_audio_partial('is weak')
        await asyncio.gather(cap, return_exceptions=True)
        self.assertTrue(self.s.ended)
        self.assertEqual(self.s.engine.turn_text, '')
        self.assertIsNone(self.s._cap)
