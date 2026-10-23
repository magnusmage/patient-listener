"""Safety must stop practice at the core and application boundaries."""

import asyncio
import threading
import unittest

from patient_listener.app.session import AppSession
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.types import State


class SafetyStopSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = SqliteStore(check_same_thread=False)
        self.people = seed_all(self.store)
        self.events = []
        self.sessions = []

    async def asyncTearDown(self):
        for session in self.sessions:
            session.close()
        self.store.close()

    async def session(self, person="margaret"):
        async def send(event):
            self.events.append(event)

        session = AppSession(self.store, self.people[person], send)
        self.sessions.append(session)
        await session.start()
        self.events.clear()
        return session

    async def test_all_safety_kinds_block_further_practice(self):
        for phrase, card in [
            ("my arm is weak", "stroke_signs"),
            ("I'm useless", "distress"),
            ("my voice has been hoarse for 3 weeks", "red_flag:hoarse"),
        ]:
            with self.subTest(card=card):
                session = await self.session()
                await session.handle({"type": "help"})  # stop during a hint
                await session.handle({"type": "typed", "text": phrase})
                self.assertTrue(session.ended)
                self.assertEqual(session.engine.controller.state, State.SAFETY_STOP)
                self.assertEqual(self.events[-1]["card"], card)
                count = len(self.events)
                for kind in ("help", "yes", "no", "confirm_tap", "done", "resume",
                             "start", "pause", "speech", "demo_say", "typed", "stop"):
                    await session.handle({"type": kind, "text": "Biscuit", "ok": True})
                await session.next_prompt()
                await session.start()
                self.assertEqual(len(self.events), count)
                self.assertEqual(self.store.attempts_for(session.person_id), [])

    async def test_safety_cancels_pending_prompt_and_silence_timer(self):
        session = await self.session()
        await session.handle({"type": "demo_say", "variant": "exact"})
        advance = session._advance
        await session.handle({"type": "pause"})
        ticker = session._ticker
        await session.handle({"type": "typed", "text": "my arm is weak"})
        count = len(self.events)
        await asyncio.gather(advance, ticker, return_exceptions=True)
        self.assertIsNone(session._advance)
        self.assertIsNone(session._ticker)
        self.assertEqual(len(self.events), count)
        self.assertEqual(self.events[-1]["type"], "safety")

    async def test_loudness_safety_uses_core_and_cancels_next_prompt(self):
        session = await self.session("joseph")
        await session.handle({'type':'audio_settings','auto_gain_control':False,
            'noise_suppression':False,'echo_cancellation':False,'safari':False,'changed':False})
        for _ in range(5):
            await session.on_audio_level(-23,2560)
            await session.handle({'type':'calibration_next'})
        await session.on_audio_level(-24,2560)
        advance = session._advance
        await session.handle({"type": "typed", "text": "my voice has been hoarse for 3 weeks"})
        self.assertTrue(session.ended)
        self.assertEqual(session.engine.controller.state, State.SAFETY_STOP)
        self.assertEqual(session.engine.safety_card, "red_flag:hoarse")
        count = len(self.events)
        await session.handle({"type": "typed", "text": "good morning"})
        await asyncio.gather(advance, return_exceptions=True)
        self.assertEqual(len(self.events), count)

    async def test_core_rejects_every_event_after_safety(self):
        session = await self.session()
        engine = session.engine
        # Exercise the core without the application's input guard.
        engine.feed(("heard", "my arm is weak", 1.0))
        log = list(engine.log)
        for event in [
            ("help", 2.0), ("yes", 2.0), ("no", 2.0),
            ("confirm_tap", True, 2.0), ("done", 2.0), ("stop", 2.0),
            ("speech", 2.0), ("silence", 2.0), ("silence", 30.0),
            ("heard", "Biscuit", 2.0), ("typed", "Biscuit", 2.0),
            ("prompt", session.current, "photo", 2.0),
        ]:
            with self.subTest(event=event[0]):
                self.assertEqual(engine.feed(event), [])
                self.assertEqual(engine.controller.state, State.SAFETY_STOP)
        self.assertEqual(engine.log, log)
        self.assertEqual(engine.replies, [])
        self.assertEqual(self.store.attempts_for(session.person_id), [])

    async def test_new_session_can_start_explicitly(self):
        session = await self.session()
        await session.handle({"type": "typed", "text": "my arm is weak"})
        fresh = await self.session()
        self.assertFalse(fresh.ended)
        self.assertEqual(fresh.engine.controller.state, State.LISTENING)

    async def test_cancelled_worker_finishes_before_safety_mutates_engine(self):
        session = await self.session()
        entered = threading.Event()
        release = threading.Event()
        original_feed = session.engine.feed

        def blocking_feed(event):
            if event[0] == "silence":
                entered.set()
                if not release.wait(timeout=2):
                    raise AssertionError("worker was not released")
            return original_feed(event)

        session.engine.feed = blocking_feed
        worker = asyncio.create_task(session._feed(("silence", 0.0)))
        safety = None
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            worker.cancel()
            safety = asyncio.create_task(
                session.handle({"type": "typed", "text": "my arm is weak"})
            )
            await asyncio.sleep(0)
            self.assertFalse(safety.done())
            release.set()
            await asyncio.gather(worker, safety, return_exceptions=True)
            safety.result()
            self.assertTrue(worker.cancelled())
            self.assertTrue(session.ended)
            self.assertEqual(session.engine.controller.state, State.SAFETY_STOP)
            self.assertEqual(self.events[-1]["type"], "safety")
        finally:
            release.set()
            await asyncio.gather(worker, *([safety] if safety else []), return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
