"""Real controller/app boundaries with synthetic timing; no GPU or model credits."""
import asyncio
import unittest
from unittest.mock import patch

from patient_listener.app.session import AppSession
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.types import State
from patient_listener.voice.actions import ShowHint


class VoiceTurnSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = SqliteStore(check_same_thread=False)
        self.people = seed_all(self.store)
        self.events = []
        self.sessions = []

    async def asyncTearDown(self):
        tasks = []
        for s in self.sessions:
            tasks.extend(t for t in (s._ticker,s._advance) if t is not None)
            s.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.store.close()

    async def session(self, person='margaret'):
        async def send(event): self.events.append(event)
        s = AppSession(self.store,self.people[person],send)
        self.sessions.append(s)
        await s.start()
        self.events.clear()
        return s

    async def test_spoken_yes_still_accepts_an_offered_hint(self):
        s = await self.session()
        await s._run_engine(('silence',0.0))
        await s._run_engine(('silence',7.0))
        self.assertEqual(s.engine.controller.state,State.HINT_OFFERED)
        await s.on_audio_speech()
        await s.handle({'type':'yes'})
        self.assertTrue(any(e['type']=='hint' for e in self.events))

    async def test_speech_restarts_wait_after_a_long_pause(self):
        s = await self.session()
        await s._run_engine(('silence',0.0))
        await s._run_engine(('silence',3.9))
        await s._run_engine(('speech',3.95))
        self.events.clear()
        await s._run_engine(('silence',4.0))
        await s._run_engine(('silence',7.9))
        self.assertFalse(any(e['type'] in ('backchannel','offerHint','moveOn') for e in self.events))
        await s._run_engine(('silence',8.0))
        self.assertTrue(any(e['type']=='backchannel' for e in self.events))

    async def test_words_out_block_remains_silent_and_unfinished_text_keeps_waiting(self):
        s = await self.session('daniyal')
        await s.on_audio_speech()
        await s.on_audio_final('my my my')
        await s._run_engine(('silence',0.0))
        self.events.clear()
        for second in (3.0,7.0,8.0,12.0):
            await s._run_engine(('silence',second))
        self.assertFalse(any(e['type'] in ('backchannel','offerHint','hint','reply','moveOn') for e in self.events))
        self.assertFalse(s.ended)

    async def test_partial_safety_is_terminal_and_cancels_timers(self):
        s = await self.session()
        await s.handle({'type':'pause'})
        await s.on_audio_partial('my arm is weak')
        self.assertTrue(s.ended)
        self.assertEqual(s.engine.controller.state,State.SAFETY_STOP)
        self.assertIsNone(s._ticker)
        count = len(self.events)
        await s.on_audio_final('Biscuit')
        await s.on_audio_speech()
        await s.handle({'type':'help'})
        self.assertEqual(len(self.events),count)
        self.assertEqual(self.store.attempts_for(s.person_id),[])

    async def test_prompt_advance_waits_for_playback_and_stop_unblocks_it(self):
        s = await self.session()
        s.set_audio_busy(True)
        with patch('patient_listener.app.session.asyncio.sleep',return_value=None):
            task = asyncio.create_task(s._do_advance(0))
            await asyncio.sleep(0)
        # wait() must suspend the advancement while speech is still playing.
        await asyncio.sleep(.01)
        self.assertEqual(s.idx,0)
        await s.stop()
        s.set_audio_busy(False)
        await asyncio.wait_for(task,1)
        self.assertEqual(s.idx,0)

    async def test_other_plan_words_do_not_complete_current_prompt(self):
        s = await self.session()
        self.assertEqual(s.current.text, 'Biscuit')
        for text in ('Leo', 'kettle'):
            await s.on_audio_speech()
            await s.on_audio_final(text)
            self.assertEqual(self.store.attempts_for(s.person_id), [])
            self.assertEqual(s.engine.found, set())
            self.assertIsNone(s._advance)
            self.assertIsNone(s.engine.controller.pending)
        self.assertFalse(any(e['type'] == 'found' for e in self.events))
        await s.on_audio_final('Biscuit')
        attempts = self.store.attempts_for(s.person_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]['word_id'], s.current.id)
        self.assertEqual(s.engine.found, {'Biscuit'})

    async def test_typed_wrong_word_and_yes_cannot_complete_prompt(self):
        s = await self.session()
        await s.handle({'type': 'typed', 'text': 'Leo'})
        await s.handle({'type': 'yes'})
        self.assertEqual(self.store.attempts_for(s.person_id), [])
        self.assertIsNone(s._advance)
        await s.handle({'type': 'typed', 'text': 'Biscaa'})
        self.assertEqual(s.engine.controller.state, State.CONFIRMING)
        self.assertEqual(s.engine.controller.pending.word.id, s.current.id)
        await s.handle({'type': 'yes'})
        self.assertEqual(len(self.store.attempts_for(s.person_id)), 1)
