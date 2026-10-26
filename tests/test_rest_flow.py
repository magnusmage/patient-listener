"""FR-15 rest is quiet and does not consume a practice turn."""
import asyncio
import unittest
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
