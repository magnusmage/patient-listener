"""Per-connection orchestrator: drives the real :class:`SessionEngine` for one WebSocket.

Mirrors the flow the browser's ``DemoEngine`` used to run locally - greeting, prompts, the
patience clock, turn advancement - but every *decision* (safety, matching, hints, timing,
logging) is made by the pure core. The orchestrator only owns what the core deliberately leaves
to the I/O edge: the word cursor, the wall clock, prompt advancement, and the profile-specific
feedback presentation (the loudness bar has no audio offline, so it is an explicit UI stand-in).

``SessionEngine.feed`` is synchronous and uses ``asyncio.run`` internally (for the LLM port), so
it cannot run inside this event loop; every call is dispatched to a worker thread with
``asyncio.to_thread``. That keeps the core unchanged and avoids a nested-loop error.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from ..llm.reply import TemplateLlm
from ..ports import Llm
from ..store.sqlite_store import SqliteStore
from ..types import Feedback, Need, State
from ..voice import safety as safetymod
from ..voice.actions import EndTurn, MoveOn, OfferRest, Praise, SafetyStop, Stop
from ..voice.merge import merge
from ..voice.session import SessionEngine
from ..llm import templates
from . import bridge, presenter

__all__ = ["AppSession"]

Sender = Callable[[dict], Awaitable[None]]

# How often the silence ticker re-feeds the controller while the person is quiet.
_TICK_S = 0.4
# Primary-need preference order (a stable "profile" label for the frontend).
_PROFILE_ORDER = (
    Need.FINDING_WORDS,
    Need.WORDS_OUT,
    Need.BEING_HEARD,
    Need.BEING_CLEAR,
    Need.SAVING_ENERGY,
    Need.LISTENING,
)

_RING = {
    State.LISTENING: "listening",
    State.BACKCHANNELED: "listening",
    State.CONFIRMING: "listening",
    State.SILENT: "silent",
    State.HINT_OFFERED: "hint_offered",
    State.HINTING: "hinting",
    State.PRAISING: "speaking",
    State.SPEAKING: "speaking",
}


class AppSession:
    """One live session: owns the engine, the cursor and the silence ticker."""

    def __init__(
        self,
        store: SqliteStore,
        person_id: str,
        send: Sender,
        llm: Optional[Llm] = None,
        session_id: str = "ws",
        region: str = "UK",
    ) -> None:
        self.store = store
        self.person_id = person_id
        self._send = send
        self.region = region
        self.first_name = store.person_name(person_id)
        needs = store.person_needs(person_id)
        self.cfg = merge(needs)
        self.words = store.words(person_id)
        self.profile = next((n.value for n in _PROFILE_ORDER if n in needs), "finding_words")
        self.feedback = presenter.feedback_key(self.cfg.feedback)
        self.engine = SessionEngine(
            cfg=self.cfg,
            store=store,
            llm=llm or TemplateLlm(),
            person_id=person_id,
            session_id=session_id,
            first_name=self.first_name,
            words=self.words,
            region=region,
        )
        self.idx = 0
        self.current = None
        self.ended = False
        self._t0 = 0.0
        self._loud = 0
        self._ticker: Optional[asyncio.Task] = None
        self._advance: Optional[asyncio.Task] = None
        self._engine_lock = asyncio.Lock()

    # --- clock & context ------------------------------------------------------

    def now(self) -> float:
        return asyncio.get_running_loop().time() - self._t0

    def _ctx(self) -> bridge.EmitContext:
        return bridge.EmitContext(
            feedback=self.feedback,
            last_heard=self.engine.last_heard,
            hint_level=int(self.engine.controller.level),
            found=sorted(self.engine.found),
            region=self.region,
        )

    def _state_event(self) -> Optional[dict]:
        ring = _RING.get(self.engine.controller.state)
        return {"type": "state", "state": ring} if ring else None

    # --- emit helpers ---------------------------------------------------------

    async def _emit(self, events: list[Optional[dict]]) -> None:
        for ev in events:
            if ev:
                await self._send(ev)

    async def _feed(self, event: tuple) -> list:
        """Run one engine event off the loop thread (the engine uses asyncio.run internally)."""
        async with self._engine_lock:
            task = asyncio.create_task(asyncio.to_thread(self.engine.feed, event))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Cancelling a timer cannot stop its worker thread. Keep the lock until it
                # finishes so another event cannot mutate the engine concurrently.
                await task
                raise

    async def _run_engine(self, event: tuple) -> list:
        if self.ended:
            return []
        before = len(self.engine.replies)
        acts = await self._feed(event)
        if self.ended:
            return []
        if any(isinstance(a, SafetyStop) for a in acts):
            self.ended = True
            self._cancel_ticker()
            self._cancel_advance()
        events: list[Optional[dict]] = []
        for a in acts:
            events += bridge.action_to_events(a, self._ctx())
        if len(self.engine.replies) > before:
            events.append({"type": "reply", "text": self.engine.replies[-1]})
        events.append(self._state_event())
        await self._emit(events)
        self._maybe_advance(acts)
        return acts

    # --- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        if self.ended:
            return
        self._t0 = asyncio.get_running_loop().time()
        greeting = templates.greeting(self.first_name)
        await self._emit([{"type": "greeting", "text": greeting, "caption": greeting}])
        await self.next_prompt()

    async def next_prompt(self) -> None:
        self._cancel_ticker()
        self._cancel_advance()
        if self.ended:
            return
        self.current = self.words[self.idx % len(self.words)] if self.words else None
        payload = presenter.prompt_payload(self.current, self.cfg.feedback, self.profile)
        acts = await self._feed(("prompt", self.current, payload["topic"], self.now()))
        if self.ended or self.engine.controller.state == State.SAFETY_STOP:
            return
        if any(isinstance(a, Stop) for a in acts):
            self.ended = True
            await self._emit([{"type": "ended", "reason": "done", "found": sorted(self.engine.found)}])
            return
        if any(isinstance(a, OfferRest) for a in acts):
            await self._emit([{"type": "restOffer"}])
            return
        await self._emit([{"type": "prompt", **payload}, self._state_event()])

    # --- inbound message dispatch ---------------------------------------------

    async def handle(self, msg: dict) -> None:
        if self.ended:
            return
        name, data = bridge.client_message_to_event(msg)
        if name == "start":
            await self.start()
        elif name == "pause":
            await self._pause()
        elif name == "speech":
            self._cancel_ticker()
            await self._run_engine(("speech", self.now()))
        elif name == "demo_say":
            await self._demo_say(data.get("variant", "exact"))
        elif name == "typed":
            await self._heard("typed", data.get("text", ""))
        elif name == "help":
            await self._run_engine(("help", self.now()))
        elif name == "yes":
            await self._run_engine(("yes", self.now()))
        elif name == "no":
            await self._run_engine(("no", self.now()))
        elif name == "confirm_tap":
            await self._run_engine(("confirm_tap", bool(data.get("ok", False)), self.now()))
        elif name == "done":
            await self._run_engine(("done", self.now()))
        elif name == "rest":
            await self._emit([{"type": "state", "state": "resting"}])
        elif name == "resume":
            self.idx += 1
            await self.next_prompt()
        elif name == "stop":
            await self.stop()

    async def stop(self) -> None:
        self._cancel_ticker()
        self._cancel_advance()
        if self.ended:
            return
        self.ended = True
        acts = await self._feed(("stop", self.now()))
        events: list[Optional[dict]] = []
        for a in acts:
            events += bridge.action_to_events(a, self._ctx())
        if not events:
            events = [{"type": "ended", "reason": "stop", "found": sorted(self.engine.found)}]
        await self._emit(events)

    # --- microphone / ASR input ---------------------------------------------

    async def on_audio_speech(self) -> None:
        """Streaming ASR/VAD detected speech; this immediately stops the silence clock."""
        if self.ended:
            return
        self._cancel_ticker()
        await self._run_engine(("speech", self.now()))

    async def on_audio_partial(self, text: str) -> None:
        """Forward a transient caption. Partial ASR text never reaches storage or matching."""
        if not self.ended and text:
            # Detect red flags before waiting for the ASR segment to finalize.
            if safetymod.check(text) is not None:
                await self._run_engine(("heard", text, self.now()))
                return
            await self._emit([{"type": "caption", "who": "you", "text": text, "partial": True}])

    async def on_audio_final(self, text: str) -> None:
        """A final ASR transcript follows the same safety and controller path as typed text."""
        if not self.ended and text:
            await self._heard("heard", text)

    async def on_audio_silence(self) -> None:
        """VAD found silence; resume the existing server-side patience clock."""
        if not self.ended:
            await self._pause()

    # --- heard / spoken input -------------------------------------------------

    async def _demo_say(self, variant: str) -> None:
        word = self.current.text if self.current else "I had a good weekend thanks"
        if variant == "close" and self.current:
            text = presenter.close_variant(self.current.text)
        elif variant == "other":
            text = "teapot"
        elif variant == "stroke":
            text = presenter.STROKE_PHRASE
        else:  # exact
            text = word
        await self._heard("heard", text)

    async def _heard(self, kind: str, text: str) -> None:
        self._cancel_ticker()
        # Loudness is a session feedback bar, not a word match, and needs audio we do not have
        # offline - so present it here as an explicit stand-in. Safety still runs, via the core.
        if self.feedback == Feedback.LOUDNESS.value:
            sig = safetymod.check(text)
            if sig is not None:
                await self._run_engine((kind, text, self.now()))
                return
            self._loud += 1
            strong = self._loud % 2 == 0
            events: list[Optional[dict]] = [{"type": "loudness", "strong": strong}]
            if not strong:
                events.append({"type": "reply", "text": "A bit stronger?"})
            events.append({"type": "state", "state": "listening"})
            await self._emit(events)
            self._schedule_advance(0.8)
            return
        await self._run_engine((kind, text, self.now()))

    # --- patience clock (server-side silence ticker) --------------------------

    async def _pause(self) -> None:
        self._cancel_ticker()
        self._ticker = asyncio.create_task(self._tick())

    async def _tick(self) -> None:
        try:
            if await self._silence_step():
                return
            while True:
                await asyncio.sleep(_TICK_S)
                if await self._silence_step():
                    return
        except asyncio.CancelledError:  # pragma: no cover - normal cancellation
            pass

    async def _silence_step(self) -> bool:
        """Feed one ``silence`` tick; return True when the turn has ended (stop ticking)."""
        acts = await self._run_engine(("silence", self.now()))
        return self.ended or any(isinstance(a, (MoveOn, EndTurn, Stop)) for a in acts)

    # --- turn advancement -----------------------------------------------------

    def _maybe_advance(self, acts: list) -> None:
        if self.ended:
            return
        if any(isinstance(a, Stop) for a in acts):
            self.ended = True
            return
        if any(isinstance(a, Praise) for a in acts):
            self._schedule_advance(1.6)
        elif any(isinstance(a, (MoveOn, EndTurn)) for a in acts):
            self._schedule_advance(0.9)

    def _schedule_advance(self, delay: float) -> None:
        if self.ended:
            return
        self._cancel_advance()
        self._advance = asyncio.create_task(self._do_advance(delay))

    async def _do_advance(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if self.ended:
                return
            self.idx += 1
            await self.next_prompt()
        except asyncio.CancelledError:  # pragma: no cover
            pass

    def _cancel_ticker(self) -> None:
        if self._ticker and not self._ticker.done() and self._ticker is not asyncio.current_task():
            self._ticker.cancel()
        self._ticker = None

    def _cancel_advance(self) -> None:
        if self._advance and not self._advance.done() and self._advance is not asyncio.current_task():
            self._advance.cancel()
        self._advance = None

    def close(self) -> None:
        self._cancel_ticker()
        self._cancel_advance()
