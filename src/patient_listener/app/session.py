"""Per-connection orchestrator: drives the real :class:`SessionEngine` for one WebSocket.

Mirrors the flow the browser's ``DemoEngine`` used to run locally - greeting, prompts, the
patience clock, turn advancement - but every *decision* (safety, matching, hints, timing,
logging) is made by the pure core. The orchestrator only owns what the core deliberately leaves
to the I/O edge: the word cursor, the wall clock, prompt advancement, and the profile-specific
feedback presentation. Loudness uses voiced microphone audio only, never typed text.

``SessionEngine.feed`` is synchronous and uses ``asyncio.run`` internally (for the LLM port), so
it cannot run inside this event loop; every call is dispatched to a worker thread with
``asyncio.to_thread``. That keeps the core unchanged and avoids a nested-loop error.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Awaitable, Callable, Optional

from ..llm.reply import TemplateLlm
from ..ports import Llm
from ..store.sqlite_store import SqliteStore
from ..types import Feedback, Need, State
from ..voice import safety as safetymod
from ..voice.actions import EndTurn, MoveOn, OfferRest, Praise, SafetyStop, Stop
from ..voice.session import SessionEngine
from ..voice.loudness import SessionLoudness, CALIBRATION_PHRASES
from ..llm import templates
from . import bridge, presenter

__all__ = ["AppSession"]

Sender = Callable[[dict], Awaitable[None]]

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
        self.cfg = store.person_pause(person_id)
        approved = {w.id: w for w in store.words(person_id)}
        self.plan = store.load_plan(person_id)
        self.plan_items = {i.word_id: i for i in self.plan.items if i.word_id in approved}
        ordered_ids = list(dict.fromkeys(i.word_id for i in self.plan.items if i.word_id in approved))
        self.words = [approved[wid] for wid in ordered_ids] or list(approved.values())[:10]
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
            target_only=True,  # each browser prompt practices one specific item
        )
        self.idx = 0
        self.current = None
        self.ended = False
        self.closing = False
        self._started = False
        self._resting = False
        self._rest_pending_prompt = False
        self._session_limit = self.cfg.max_session_min
        self._cap: Optional[asyncio.Task] = None
        self._t0 = 0.0
        self.loudness = SessionLoudness()
        self._capture_ready = False
        self._loudness_skipped = False
        self._capture_settings = None
        self._sleep = asyncio.sleep  # Injected by fake-clock scheduling tests.
        self._ticker: Optional[asyncio.Task] = None
        self._advance: Optional[asyncio.Task] = None
        self._engine_lock = asyncio.Lock()
        self._audio_idle = asyncio.Event()
        self._audio_idle.set()

    def set_audio_busy(self, busy: bool) -> None:
        """Prevent advancing to another prompt before browser playback completes."""
        if busy:
            self._audio_idle.clear()
        else:
            self._audio_idle.set()

    # --- clock & context ------------------------------------------------------

    def now(self) -> float:
        return asyncio.get_running_loop().time() - self._t0

    def _ctx(self) -> bridge.EmitContext:
        return bridge.EmitContext(
            feedback=(Feedback.WHAT_I_HEARD.value if Feedback.WHAT_I_HEARD in self.cfg.feedback
                      else self.feedback),
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
        if self.ended or self.closing:
            return []
        if self._resting and event[0] != 'stop':
            if event[0] not in ('typed', 'heard') or safetymod.check(event[1]) is None:
                return []
        before = len(self.engine.replies)
        acts = await self._feed(event)
        if self.ended or self.closing:
            return []
        if any(isinstance(a, SafetyStop) for a in acts):
            self.ended = True
            self._cancel_ticker()
            self._cancel_advance()
            self._cancel_cap()
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
        if self.ended or self._started:
            return
        self._started = True
        self._t0 = asyncio.get_running_loop().time()
        self._session_limit = self.cfg.max_session_min
        self._arm_cap()
        greeting = templates.greeting(self.first_name)
        await self._emit([{"type": "greeting", "text": greeting, "caption": greeting}])
        await self.next_prompt()

    async def next_prompt(self, *, resuming: bool = False) -> None:
        self._cancel_ticker()
        self._cancel_advance()
        if self.ended or self.closing:
            return
        if self.calibrating:
            await self._calibration_prompt()
            return
        self.current = self.words[self.idx % len(self.words)] if self.words else None
        payload = presenter.prompt_payload(self.current, self.cfg.feedback, self.profile)
        if Feedback.LOUDNESS in self.cfg.feedback and (not self._capture_ready or self._loudness_skipped):
            payload['instruction'] = 'Voice level is unavailable with these microphone settings. You can still practise by talking or typing.'
        item = self.plan_items.get(self.current.id) if self.current else None
        if item is not None:
            payload["text"] = item.prompt
        # An automatic rest has already reserved this turn and target. Resume it
        # without incrementing the turn count or skipping the unpresented item.
        acts = [] if resuming else await self._feed(("prompt", self.current, payload["topic"], self.now()))
        if self.ended or self.engine.controller.state == State.SAFETY_STOP:
            return
        if any(isinstance(a, Stop) for a in acts):
            await self._finish("turn_cap")
            return
        if any(isinstance(a, OfferRest) for a in acts):
            self._resting = self._rest_pending_prompt = True
            await self._emit([{"type": "restOffer"}])
            return
        self._resting = self._rest_pending_prompt = False
        await self._emit([{"type": "prompt", **payload}, self._state_event()])

    # --- inbound message dispatch ---------------------------------------------

    async def handle(self, msg: dict) -> None:
        if self.ended:
            return
        name, data = bridge.client_message_to_event(msg)
        if self.closing and name != "stop":
            return
        if self.calibrating and name in {'help', 'yes', 'no', 'done', 'confirm_tap',
                                          'pause', 'speech', 'resume', 'rest', 'demo_say'}:
            return
        if name == 'audio_settings':
            await self._audio_settings(data)
        elif name == 'calibration_skip':
            if data:
                raise ValueError('calibration_skip takes no arguments')
            if self.calibrating:
                self._loudness_skipped = True
                self.loudness = SessionLoudness()
                await self.next_prompt()
        elif name == 'calibration_next':
            if data:
                raise ValueError('calibration_next takes no arguments')
            if self.calibrating and self._audio_idle.is_set() and self.loudness.accept_phrase():
                await self.next_prompt()
        elif name == "extend_session":
            if set(data) != {"minutes"}:
                raise ValueError("extend_session requires minutes only")
            await self._extend_settings({"max_session_min": data["minutes"]})
        elif name == "extend_settings":
            await self._extend_settings(data)
        elif name == "start":
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
            await self._run_engine(("confirm_tap", data["ok"], self.now()))
        elif name == "done":
            await self._run_engine(("done", self.now()))
        elif name == "rest":
            self._resting = True
            self._cancel_ticker()
            self._cancel_advance()
            await self._emit([{"type": "state", "state": "resting", "replace_audio": True}])
        elif name == "resume":
            if not self._resting:
                return
            pending = self._rest_pending_prompt
            self._resting = False
            if not pending:
                self.idx += 1
            await self.next_prompt(resuming=pending)
        elif name == "stop":
            await self.stop()

    async def stop(self) -> None:
        self._cancel_ticker()
        self._cancel_advance()
        self._cancel_cap()
        self.closing = False
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
        if self.ended or self.closing:
            return
        self._cancel_ticker()
        if not self.calibrating:
            await self._run_engine(("speech", self.now()))

    async def on_audio_partial(self, text: str) -> None:
        """Forward a transient caption. Partial ASR text never reaches storage or matching."""
        if not self.ended and not self.closing and text:
            # Detect red flags before waiting for the ASR segment to finalize.
            combined = " ".join(part for part in (self.engine.turn_text, text) if part)
            if safetymod.check(combined) is not None:
                await self._run_engine(("typed", combined, self.now()))
                return
            await self._emit([{"type": "caption", "who": "you", "text": text, "partial": True}])

    async def on_audio_final(self, text: str) -> None:
        """A final ASR transcript follows the same safety and controller path as typed text."""
        if not self.ended and not self.closing and text:
            await self._heard("heard", text)

    async def on_audio_silence(self) -> None:
        """VAD found silence; resume the existing server-side patience clock."""
        if not self.ended and not self.closing:
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
        if Feedback.LOUDNESS in self.cfg.feedback:
            # Safety is evaluated before calibration or feedback, including typed input.
            if safetymod.check(text) is not None:
                await self._run_engine((kind, text, self.now()))
                return
            if self.calibrating:
                await self._emit([{'type': 'caption', 'who': 'you', 'text': text}])
                return
        await self._run_engine((kind, text, self.now()))

    @property
    def calibrating(self):
        return (Feedback.LOUDNESS in self.cfg.feedback and self._capture_ready
                and not self._loudness_skipped and self.loudness.baseline is None)

    async def _audio_settings(self, values):
        allowed = {'auto_gain_control', 'noise_suppression', 'echo_cancellation', 'safari', 'changed'}
        if (set(values) != allowed or any(type(values[k]) is not bool for k in ('safari', 'changed'))
                or any(values[k] is not None and type(values[k]) is not bool
                       for k in ('auto_gain_control', 'noise_suppression', 'echo_cancellation'))):
            raise ValueError('Invalid microphone settings')
        settings = tuple(values[k] for k in sorted(allowed - {'changed'}))
        changed = values['changed'] or self._capture_settings != settings
        self._capture_settings = settings
        self._capture_ready = (values['auto_gain_control'] is False
                               and values['noise_suppression'] is False
                               and values['echo_cancellation'] is values['safari'])
        if changed:
            self.loudness = SessionLoudness()
            if self._started and Feedback.LOUDNESS in self.cfg.feedback:
                self._cancel_ticker()
                self._cancel_advance()
                # Never wait inside the socket reader: playback ACKs arrive there too.
                async def restart():
                    await self._audio_idle.wait()
                    if not self.ended and not self.closing:
                        await self.next_prompt()
                self._advance = asyncio.create_task(restart())

    async def _calibration_prompt(self):
        phrase = CALIBRATION_PHRASES[len(self.loudness.phrases)]
        await self._emit([{'type': 'prompt', 'text': phrase, 'photo': '',
            'topic': 'voice setup', 'profile': self.profile, 'feedback': self.feedback,
            'calibration': True,
            'instruction': "Keep one hand's width from the microphone. Read in your comfortable strong voice, then pause and tap Use this phrase."},
            {'type': 'state', 'state': 'listening'}])

    async def on_audio_level(self, level, count):
        if (self.ended or self.closing or not self._started or not self._audio_idle.is_set()
                or Feedback.LOUDNESS not in self.cfg.feedback or not self._capture_ready
                or self._loudness_skipped):
            return
        if self.calibrating:
            if self.loudness.observe(level, count):
                await self._emit([{'type': 'calibrationReady', 'ready': True}])
            return
        import math
        if (not isinstance(level, (int, float)) or not math.isfinite(level)
                or not -120 <= level <= 1 or type(count) is not int or count < 1600):
            return
        event = self.loudness.feedback(level)
        await self._emit([event])
        if not event['strong']:
            await self._emit([{'type': 'reply', 'text': 'A bit stronger?'}])
        if self.current is None and self.engine.controller.state != State.CONFIRMING:
            self._schedule_advance(0.8)

    # --- patience clock (server-side silence ticker) --------------------------

    async def _pause(self) -> None:
        if self.calibrating or self._resting:
            return
        self._cancel_ticker()
        self._ticker = asyncio.create_task(self._tick())

    async def _tick(self) -> None:
        try:
            if await self._silence_step():
                return
            while not self.ended and not self.closing:
                deadline = self.engine.controller.next_silence_deadline(self.now())
                if deadline is None:
                    return
                await self._sleep(max(0.0, deadline - self.now()))
                if self.ended or self.closing or await self._silence_step():
                    return
        except asyncio.CancelledError:  # pragma: no cover - normal cancellation
            pass

    async def _silence_step(self) -> bool:
        """Feed one ``silence`` tick; return True when the turn has ended (stop ticking)."""
        acts = await self._run_engine(("silence", self.now()))
        return self.ended or self.closing or any(isinstance(a, (MoveOn, EndTurn, Stop)) for a in acts)

    # --- turn advancement -----------------------------------------------------

    def _maybe_advance(self, acts: list) -> None:
        if self.ended:
            return
        if any(isinstance(a, Stop) for a in acts):
            self.ended = True
            self._cancel_cap()
            return
        if any(isinstance(a, Praise) for a in acts):
            self._schedule_advance(1.6)
        elif any(isinstance(a, (MoveOn, EndTurn)) for a in acts):
            self._schedule_advance(0.9)

    def _schedule_advance(self, delay: float) -> None:
        if self.ended or self._resting:
            return
        self._cancel_advance()
        self._advance = asyncio.create_task(self._do_advance(delay))

    async def _do_advance(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._audio_idle.wait()
            if self.ended or self._resting:
                return
            self.idx += 1
            await self.next_prompt()
        except asyncio.CancelledError:  # pragma: no cover
            pass

    # --- elapsed-session cap (includes rests; never resets on another Start) ---

    def _cancel_cap(self) -> None:
        if self._cap and self._cap is asyncio.current_task():
            return
        if self._cap and not self._cap.done():
            self._cap.cancel()
        self._cap = None

    def _arm_cap(self) -> None:
        self._cancel_cap()
        if self._started and self._session_limit is not None and not self.ended:
            self._cap = asyncio.create_task(self._watch_cap())

    async def _extend_settings(self, changes: dict) -> None:
        from ..profile_settings import extend_only
        async with self._engine_lock:
            if self.ended or self.closing:
                return
            current = replace(self.cfg, max_session_min=self._session_limit)
            try:
                clean = extend_only(current, changes)
                self.store.patient_extend_profile(self.person_id, clean)
            except PermissionError as exc:
                raise ValueError(str(exc)) from exc  # invalid WebSocket control
            self.cfg = replace(current, **clean)
            self.engine.cfg = self.cfg
            self.engine.controller.cfg = self.cfg
        if 'max_session_min' in clean:
            self._session_limit = clean['max_session_min']
            self._arm_cap()
        await self._emit([{"type": "settingsSaved"}])

    async def _watch_cap(self) -> None:
        try:
            while not self.ended and not self.closing and self._session_limit is not None:
                remaining = self._session_limit * 60 - self.now()
                if remaining <= 0:
                    await self._finish("session_cap")
                    return
                await asyncio.sleep(remaining)
        except asyncio.CancelledError:
            pass
        finally:
            if self._cap is asyncio.current_task():
                self._cap = None

    async def _finish(self, reason: str) -> None:
        if self.ended or self.closing:
            return
        self.closing = True
        self._cancel_ticker()
        self._cancel_advance()
        self._cancel_cap()
        # Replace pending practice audio, then allow the fixed closing line to finish.
        await self._emit([{"type": "reply", "text": "Well done today.", "replace_audio": True}])
        await self._audio_idle.wait()
        if self.ended:  # Stop/disconnect can interrupt the closing line.
            return
        await self._feed(("stop", self.now()))
        if self.ended:
            return
        self.ended = True
        self.closing = False
        await self._emit([{"type": "ended", "reason": reason, "found": sorted(self.engine.found)}])

    def _cancel_ticker(self) -> None:
        if self._ticker and not self._ticker.done() and self._ticker is not asyncio.current_task():
            self._ticker.cancel()
        self._ticker = None

    def _cancel_advance(self) -> None:
        if self._advance and not self._advance.done() and self._advance is not asyncio.current_task():
            self._advance.cancel()
        self._advance = None

    def close(self) -> None:
        self.ended = True
        self.closing = False
        self._cancel_cap()
        self._audio_idle.set()
        self.loudness = SessionLoudness()
        self._cancel_ticker()
        self._cancel_advance()
