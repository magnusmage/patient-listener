"""FR-15 rest is quiet and does not consume a practice turn."""
import asyncio
import unittest
import threading
from dataclasses import replace
from unittest.mock import patch
from patient_listener.types import Feedback
from patient_listener.voice.actions import Speak
from patient_listener.app.session import AppSession
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all


class RestFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = SqliteStore(check_same_thread=False, ai_enabled=False)
        self.pid = seed_all(self.store)['margaret']
        self.store.set_console_user('rest-helper','Helper','therapist')
        self.store.link_console_user('rest-helper', self.pid)
        self.store.console_update_profile(self.pid, {'needs':['saving_energy']}, actor='rest-helper')
        self.events = []
        async def send(event): self.events.append(event)
        self.s = AppSession(self.store, self.pid, send)
        await self.s.start()
        self.events.clear()

    async def asyncTearDown(self):
        tasks = [t for t in (self.s._cap, self.s._ticker, self.s._advance) if t is not None]
        self.s.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.store.close()

    async def test_automatic_rest_resumes_reserved_target_without_extra_turn(self):
        for _ in range(5):
            self.s.idx += 1
            await self.s.next_prompt()
        self.assertTrue(self.s._resting)
        self.assertEqual(self.s.engine.controller.turns, 6)
        reserved = self.s.current.id
        index = self.s.idx
        self.events.clear()
        await self.s.handle({'type':'resume'})
        self.assertEqual(self.s.engine.controller.turns, 6)
        self.assertEqual(self.s.idx, index)
        self.assertEqual(self.s.current.id, reserved)
        self.assertTrue(any(e['type'] == 'prompt' for e in self.events))
        self.assertFalse(self.s._resting)

    async def test_exactly_fifteen_prompts_and_two_rests_before_cap(self):
        prompts = 1
        rests = 0
        for _ in range(20):
            self.s.idx += 1
            self.events.clear()
            await self.s.next_prompt()
            if self.s._resting:
                rests += 1
                await self.s.handle({'type':'resume'})
            prompts += sum(e['type'] == 'prompt' for e in self.events)
            if self.s.ended: break
        self.assertEqual(prompts, 15)
        self.assertEqual(rests, 2)
        self.assertTrue(self.s.ended)
        self.assertTrue(any(e.get('reason') == 'turn_cap' for e in self.events))

    async def test_manual_rest_cancels_timers_and_ignores_practice_but_allows_stop(self):
        await self.s._pause()
        ticker = self.s._ticker
        self.s._schedule_advance(100)
        advance = self.s._advance
        await self.s.handle({'type':'rest'})
        await asyncio.gather(ticker, advance, return_exceptions=True)
        self.assertIsNone(self.s._ticker)
        self.assertIsNone(self.s._advance)
        self.assertTrue(self.events[-1]['replace_audio'])
        self.events.clear()
        await self.s.on_audio_silence()
        await self.s.on_audio_final(self.s.current.text)
        await self.s.handle({'type':'help'})
        self.assertEqual(self.events, [])
        self.assertEqual(self.store.attempts_for(self.pid), [])
        await self.s.handle({'type':'stop'})
        self.assertTrue(self.s.ended)

    async def test_safety_remains_active_during_rest(self):
        await self.s.handle({'type':'rest'})
        self.events.clear()
        await self.s.on_audio_final('my arm is weak')
        self.assertTrue(self.s.ended)
        self.assertTrue(any(e['type'] == 'safety' for e in self.events))

    async def test_resume_without_rest_does_not_skip_a_prompt(self):
        index = self.s.idx
        turns = self.s.engine.controller.turns
        await self.s.handle({'type':'resume'})
        self.assertEqual(self.s.idx, index)
        self.assertEqual(self.s.engine.controller.turns, turns)
        self.assertEqual(self.events, [])


    async def test_partial_final_and_typed_answers_are_quiet_during_rest(self):
        await self.s.handle({'type':'rest'})
        self.events.clear()
        before=self.s.engine.turn_text
        await self.s.on_audio_speech()
        await self.s.on_audio_partial('some ordinary words')
        await self.s.on_audio_final(self.s.current.text)
        await self.s.handle({'type':'typed','text':self.s.current.text})
        await self.s.on_audio_silence()
        self.assertEqual(self.events,[])
        self.assertEqual(self.s.engine.turn_text,before)
        self.assertEqual(self.store.attempts_for(self.pid),[])
        self.assertIsNone(self.s._ticker)

    async def test_partial_safety_is_still_terminal_during_rest(self):
        await self.s.handle({'type':'rest'})
        self.events.clear()
        await self.s.on_audio_partial('my arm is weak')
        self.assertTrue(self.s.ended)
        self.assertTrue(any(e['type']=='safety' for e in self.events))

    async def test_spoken_stop_partial_ends_rest(self):
        await self.s.handle({'type':'rest'})
        self.events.clear()
        await self.s.on_audio_partial('Stop!')
        self.assertTrue(self.s.ended)
        self.assertTrue(any(e['type']=='ended' for e in self.events))

    async def test_combined_loudness_profile_does_not_emit_calibration_or_feedback_in_rest(self):
        self.s.cfg=replace(self.s.cfg,feedback=self.s.cfg.feedback | {Feedback.LOUDNESS})
        self.s._capture_ready=True
        await self.s.handle({'type':'rest'})
        self.events.clear()
        with patch.object(self.s.loudness,'observe',side_effect=AssertionError('No calibration in rest')):
            await self.s.on_audio_level(-30,3200)
        await self.s.on_audio_final('ordinary calibration words')
        await self.s.handle({'type':'calibration_next'})
        await self.s.handle({'type':'calibration_skip'})
        await self.s.handle({'type':'audio_settings','auto_gain_control':False,
            'noise_suppression':False,'echo_cancellation':False,'safari':False,'changed':True})
        self.assertEqual(self.events,[])
        self.assertIsNone(self.s._advance)
        self.assertTrue(self.s._resting)

    async def test_resume_restores_normal_captions(self):
        await self.s.handle({'type':'rest'})
        await self.s.handle({'type':'resume'})
        self.events.clear()
        await self.s.on_audio_partial('ordinary words')
        self.assertTrue(any(e['type']=='caption' for e in self.events))

    async def test_queued_practice_event_does_not_run_after_rest_transition(self):
        await self.s._engine_lock.acquire()
        with patch.object(self.s.engine,'feed',wraps=self.s.engine.feed) as feed:
            task=asyncio.create_task(self.s._run_engine(('typed',self.s.current.text,self.s.now())))
            await asyncio.sleep(0)
            await self.s.handle({'type':'rest'})
            self.s._engine_lock.release()
            await task
            feed.assert_not_called()
        self.assertEqual(self.store.attempts_for(self.pid),[])

    async def test_late_worker_reply_does_not_escape_rest(self):
        entered,release=threading.Event(),threading.Event()
        def slow_feed(event):
            entered.set()
            release.wait(3)
            return [Speak('An old reply.')]
        with patch.object(self.s.engine,'feed',side_effect=slow_feed):
            task=asyncio.create_task(self.s._run_engine(('done',self.s.now())))
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                await self.s.handle({'type':'rest'})
                self.events.clear()
                release.set()
                await task
                self.assertEqual(self.events,[])
                self.assertIsNone(self.s._advance)
            finally:
                release.set()
                await task

    async def test_safety_queued_before_rest_is_not_lost(self):
        await self.s._engine_lock.acquire()
        task=asyncio.create_task(self.s._run_engine(('typed','my arm is weak',self.s.now())))
        await asyncio.sleep(0)
        await self.s.handle({'type':'rest'})
        self.s._engine_lock.release()
        await task
        self.assertTrue(self.s.ended)
        self.assertTrue(any(e['type']=='safety' for e in self.events))

    async def test_cap_can_still_finish_rest(self):
        await self.s.handle({'type':'rest'})
        self.events.clear()
        await self.s._finish('session_cap')
        self.assertTrue(self.s.ended)
        self.assertTrue(any(e['type']=='ended' for e in self.events))
        self.assertTrue(any(e['type']=='reply' and e['text']=='Well done today.' for e in self.events))


    async def test_late_reply_is_suppressed_even_if_resume_happens_first(self):
        entered,release=threading.Event(),threading.Event()
        original=self.s.engine.feed
        def slow_feed(event):
            if event[0]=='done':
                entered.set()
                release.wait(3)
                return [Speak('An old reply.')]
            return original(event)
        with patch.object(self.s.engine,'feed',side_effect=slow_feed):
            task=asyncio.create_task(self.s._run_engine(('done',self.s.now())))
            resume=None
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                await self.s.handle({'type':'rest'})
                self.events.clear()
                resume=asyncio.create_task(self.s.handle({'type':'resume'}))
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(task,resume)
                self.assertFalse(any(e.get('text')=='An old reply.' for e in self.events))
                self.assertTrue(any(e['type']=='prompt' for e in self.events))
                self.assertFalse(self.s._resting)
            finally:
                release.set()
                await asyncio.gather(task,*([resume] if resume is not None else []),return_exceptions=True)
