"""Session engine: the logic-level voice loop (the ``e2e_sim`` harness).

Drives :class:`PatienceController` from a scripted list of events with an injected clock, so a
whole turn - or a whole scenario - can be exercised with no audio, no GPU and no network. It
runs safety first on anything heard or typed (FR-80/81/82), resolves the Getting-words-out
``CheckComplete`` against the ``Llm`` port, logs attempts to the store (FR-23), and runs the
validated reply step (FR-24). An "interruption" counter proves NFR-03: the listener never
emits audio while the person is speaking.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from ..ports import Llm, Store
from ..schemas import PauseConfig, ReplyFacts, WordEntry
from ..types import HintLevel, Need, State
from . import safety as safetymod
from .actions import (
    Action,
    CheckComplete,
    EndTurn,
    LogAttempt,
    MoveOn,
    Play,
    Praise,
    ShowHint,
    Speak,
    Stop,
)
from .controller import PatienceController


@dataclass
class FakeClock:
    """Injectable clock for deterministic timing tests."""

    t: float = 0.0

    def now(self) -> float:
        return self.t

    def set(self, t: float) -> None:
        self.t = t


# Actions that are legitimate inside a pause of up to 15 s (not interruptions).
_PAUSE_OK = {"mm", "offer_hint"}


@dataclass
class SessionEngine:
    cfg: PauseConfig
    store: Store
    llm: Llm
    person_id: str = "demo"
    session_id: str = "sess"
    first_name: str = "Margaret"
    words: list[WordEntry] = field(default_factory=list)
    region: str = "UK"
    target_only: bool = False

    controller: PatienceController = field(init=False)
    found: set[str] = field(default_factory=set)  # word texts found this session
    last_heard: str = ""
    turn_text: str = ""  # finalized segments for this turn only; never persisted
    topic: str = "photo"
    safety_card: Optional[str] = None
    carer_alerted: bool = False
    person_speaking: bool = False
    interruptions: int = 0
    replies: list[str] = field(default_factory=list)
    log: list[Action] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.controller = PatienceController(
            cfg=self.cfg,
            session_id=self.session_id,
            words=self.words,
            target_only=self.target_only,
        )

    # --- helpers --------------------------------------------------------------

    def _allowed_names(self) -> frozenset[str]:
        names = {self.first_name} | {w.text for w in self.words}
        return frozenset(names)

    def _reply_facts(self) -> ReplyFacts:
        heard = self.turn_text if self.cfg.needs_complete_text else " ".join(self.turn_text.split()[-20:])
        return ReplyFacts(
            person_first_name=self.first_name,
            topic=self.topic,
            hint_level=self.controller.level,
            practice_words=tuple(w.text for w in self.words),
            found=tuple(sorted(self.found)),
            last_words_heard=heard,
            needs=self.cfg.needs,
            allowed_names=self._allowed_names(),
            names_heard_this_turn=frozenset(),
            pending_confirm=self.controller.state == State.CONFIRMING,
            banned_phrases=self.cfg.banned_phrases,
        )

    def _run_reply(self) -> None:
        from ..llm.reply import produce_reply

        facts = self._reply_facts()
        result = asyncio.run(
            produce_reply(
                self.llm, facts, timeout_s=1.5, ai_enabled=self.store.is_ai_enabled
            )
        )
        logging.getLogger("uvicorn.error.patient_listener.llm").info(
            "Live reply source=%s", "template" if result.used_template else "model")
        self.replies.append(result.text)
        self._emit([Speak(result.text)], from_speech=False)

    def _emit(self, acts: list[Action], from_speech: bool) -> list[Action]:
        for a in acts:
            self.log.append(a)
            # Interruption check (NFR-03): audio while the person is speaking, or a non-allowed
            # line inside a pause.
            if isinstance(a, (Play, Speak, ShowHint)):
                if self.person_speaking:
                    self.interruptions += 1
                elif isinstance(a, Play) and a.key not in _PAUSE_OK and not a.key.startswith(
                    "hint:"
                ):
                    self.interruptions += 1
            if isinstance(a, LogAttempt):
                self.store.log_attempt(a.attempt)
                if a.attempt.outcome.value == "found":
                    w = next((x for x in self.words if x.id == a.attempt.word_id), None)
                    if w:
                        self.found.add(w.text)
            if isinstance(a, Praise):
                self.found.add(a.word.text)
            if isinstance(a, safetymod.SafetyKind):  # pragma: no cover
                pass
        return acts

    # --- event feed -----------------------------------------------------------

    def feed(self, event: tuple) -> list[Action]:
        # Safety is terminal for this engine; a new session needs a new engine.
        if self.controller.state in (State.SAFETY_STOP, State.ENDED):
            return []
        kind = event[0]
        now = event[-1] if isinstance(event[-1], (int, float)) else 0.0

        if kind == "prompt":
            self.last_heard = ""
            self.turn_text = ""
            target = event[1]
            self.topic = event[2] if len(event) > 3 else self.topic
            self.person_speaking = False
            return self._emit(self.controller.on_prompt(target, now), from_speech=False)

        if kind == "speech":
            self.person_speaking = True
            return self._emit(self.controller.on_speech(now), from_speech=True)

        if kind == "silence":
            self.person_speaking = False
            acts = self.controller.on_silence(now)
            # Resolve a Getting-words-out completeness check against the LLM.
            if any(isinstance(a, CheckComplete) for a in acts):
                question = self.topic
                complete = False
                if self.store.is_ai_enabled():
                    try:
                        async def check_complete():
                            return await asyncio.wait_for(
                                self.llm.is_complete(question, self.turn_text, timeout_s=1.0),
                                timeout=1.0,
                            )
                        complete = asyncio.run(check_complete()) and self.store.is_ai_enabled()
                    except Exception:
                        # Uncertainty means keep waiting; Done remains available.
                        complete = False
                acts = [a for a in acts if not isinstance(a, CheckComplete)]
                acts += self.controller.on_complete(complete, now)
            emitted = self._emit(acts, from_speech=False)
            if any(isinstance(a, (EndTurn, MoveOn)) for a in emitted):
                self._run_reply()
            return emitted

        if kind in ("heard", "typed"):
            text = event[1]
            self.last_heard = text
            if kind == "typed":
                self.turn_text = text.strip()  # a typed answer can replace/edit speech
            else:
                self.turn_text = " ".join(part for part in (self.turn_text, text.strip()) if part)
            sig = safetymod.check(self.turn_text)
            if sig is not None:
                self.turn_text = self.last_heard = ""
                self.safety_card = sig.card
                self.controller.state = State.SAFETY_STOP
                self.controller.pending = None
                self.controller.silence_started = None
                self.person_speaking = False
                if sig.kind == safetymod.SafetyKind.STROKE:
                    self.carer_alerted = True
                if sig.kind == safetymod.SafetyKind.DISTRESS and self.store.has_consent(
                    self.person_id, "tell_carer_low_mood"
                ):
                    self.carer_alerted = True
                from .actions import SafetyStop

                self.log.append(SafetyStop(sig.card))
                return [SafetyStop(sig.card)]
            self.person_speaking = False  # the utterance ended
            tokens = text.split()
            acts = self.controller.on_heard(tokens, now)
            emitted = self._emit(acts, from_speech=False)
            if any(isinstance(a, Praise) for a in emitted):
                self._run_reply()
            return emitted

        if kind == "help":
            return self._emit(self.controller.on_help(now), from_speech=False)

        if kind == "yes":
            acts = self.controller.on_answer(True, now)
            emitted = self._emit(acts, from_speech=False)
            if any(isinstance(a, Praise) for a in emitted):
                self._run_reply()
            return emitted

        if kind == "no":
            return self._emit(self.controller.on_answer(False, now), from_speech=False)

        if kind == "confirm_tap":
            ok = event[1]
            if not isinstance(ok, bool):
                raise ValueError("confirm_tap requires a boolean ok")
            acts = self.controller.on_answer(ok, now, via_tap=True)
            emitted = self._emit(acts, from_speech=False)
            if any(isinstance(a, Praise) for a in emitted):
                self._run_reply()
            return emitted

        if kind == "done":
            emitted = self._emit(self.controller.on_done(now), from_speech=False)
            if any(isinstance(a, EndTurn) for a in emitted):
                self._run_reply()
            return emitted

        if kind == "stop":
            self.turn_text = self.last_heard = ""
            return self._emit(self.controller.on_stop(now), from_speech=False)

        raise ValueError(f"unknown event: {kind}")

    def run(self, events: list[tuple]) -> "SessionEngine":
        for ev in events:
            self.feed(ev)
        return self
