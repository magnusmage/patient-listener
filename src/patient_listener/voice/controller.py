"""The patience controller (workbook: Developer guide -> The controller, in code; AI and
safety -> The patience controller). Invariant #1: pure code, no I/O, clock injected via the
``now`` argument, so every timing decision is unit-testable with a fake clock.

The state machine is the Finding words profile; a merged :class:`PauseConfig` switches states
on or off and changes their timing. Speech always wins: any speech frame (including "um")
resets the silence clock and nothing is ever said over the person. A plan word heard in any
state goes straight to Confirming, so finding it without a hint is the normal path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..schemas import Attempt, PauseConfig, WordEntry
from ..types import HintLevel, Need, Outcome, State
from . import hints as hintmod
from .actions import (
    Action,
    CheckComplete,
    Confirm,
    EndTurn,
    LogAttempt,
    MoveOn,
    OfferRest,
    Play,
    Praise,
    ShowHint,
    Stop,
)
from .matcher import Match, best_match


@dataclass
class PatienceController:
    cfg: PauseConfig
    session_id: str = "sess"
    target: Optional[WordEntry] = None
    words: list[WordEntry] = field(default_factory=list)  # approved list, for matching
    state: State = State.LISTENING
    silence_started: Optional[float] = None
    backchannels: int = 0
    level: HintLevel = HintLevel.NONE
    checked_complete: bool = False
    turn_started_at: Optional[float] = None
    pending: Optional[Match] = None  # a 0.60-0.89 (or Being clear) match awaiting confirm
    turns: int = 0
    logged_this_turn: bool = False

    # --- turn lifecycle -------------------------------------------------------

    def on_prompt(self, target: Optional[WordEntry], now: float = 0.0) -> list[Action]:
        """A new question starts a new turn: reset per-turn counters.

        Honours Saving energy caps: ends the session at ``max_turns`` and offers a rest every
        ``rest_every_turns`` (FR-15).
        """
        self.turns += 1
        if self.cfg.max_turns is not None and self.turns > self.cfg.max_turns:
            self.state = State.ENDED
            return [Stop()]

        self.target = target
        self.level = HintLevel.NONE
        self.backchannels = 0
        self.silence_started = None
        self.checked_complete = False
        self.turn_started_at = now
        self.pending = None
        self.logged_this_turn = False
        self.state = State.LISTENING

        rest = self.cfg.rest_every_turns
        if rest is not None and self.turns > 1 and (self.turns - 1) % rest == 0:
            return [OfferRest()]
        return []

    # --- events from VAD / ASR ------------------------------------------------

    def on_speech(self, now: float) -> list[Action]:
        """Any sound of speech resets the silence clock; we never talk over speech."""
        self.silence_started = None
        self.checked_complete = False  # the 'mm' cap is per turn, not per silence
        if self.state in (State.SILENT, State.BACKCHANNELED, State.HINT_OFFERED):
            self.state = State.LISTENING
        return []

    def on_silence(self, now: float) -> list[Action]:
        if self.silence_started is None:
            self.silence_started = now
            self.state = State.SILENT
            return []
        quiet = now - self.silence_started

        def past(limit: Optional[float]) -> bool:  # None = never (profile)
            return limit is not None and quiet >= limit

        if past(self.cfg.max_wait_s):
            if not self.cfg.needs_complete_text:
                return self._move_on(now)
            if not self.checked_complete:
                self.checked_complete = True
                return [CheckComplete()]  # adapter asks Lightning (1.0 s -> keep waiting)
            return []  # wait for on_complete(), speech or Done

        if past(self.cfg.offer_hint_s) and self.state != State.HINT_OFFERED and self.target:
            self.state = State.HINT_OFFERED
            return [Play("offer_hint")]  # "Want a hint?"

        if (
            past(self.cfg.backchannel_s)
            and self.state == State.SILENT
            and self.backchannels < self.cfg.max_backchannels_per_turn
        ):
            self.backchannels += 1
            self.state = State.BACKCHANNELED
            return [Play("mm")]  # quiet listening sound

        return []

    def on_complete(self, complete: bool, now: float) -> list[Action]:
        """Getting words out: Lightning's verdict on whether the transcript reads complete."""
        if complete:
            return self._end_turn()
        self.silence_started = now  # not finished: start waiting again
        self.checked_complete = False
        return []

    # --- help / hints ---------------------------------------------------------

    def on_help(self, now: float = 0.0) -> list[Action]:
        """Advance the hint ladder (never for a stammer; nothing to hint without a target)."""
        if Need.WORDS_OUT in self.cfg.needs or self.target is None:
            return []
        self.level = hintmod.next_level(self.level, self.cfg.hint_order)
        self.state = State.HINTING
        self.silence_started = None
        return [ShowHint(self.target, self.level), Play(f"hint:{self.target.id}:{int(self.level)}")]

    # --- yes / no -------------------------------------------------------------

    def on_answer(self, yes: bool, now: float) -> list[Action]:
        if self.state == State.HINT_OFFERED:
            if yes:
                return self.on_help(now)
            self.state = State.LISTENING  # 'no' -> back to listening, clock restarts
            self.silence_started = None
            return []
        if self.state == State.CONFIRMING and self.pending is not None:
            if yes:
                match = self.pending
                self.pending = None
                return self._found(match, now, confirmed=True)
            # 'no': not this word. Clear and keep going (a later Help advances the ladder).
            self.pending = None
            self.state = State.LISTENING
            self.silence_started = None
            return []
        return []

    # --- a word was heard -----------------------------------------------------

    def on_heard(self, tokens: list[str], now: float) -> list[Action]:
        """Run the matcher against the word list. A model never decides success (FR-22)."""
        match = best_match(tokens, self.words)
        if match is None:
            return []  # below 0.60: treated as speech; the reply step handles it

        being_clear = Need.BEING_CLEAR in self.cfg.needs
        if being_clear:
            # Nothing is logged as found until the person taps the check (FR-14).
            self.pending = match
            self.state = State.CONFIRMING
            return [Confirm(match.word)]

        if match.is_found:
            return self._found(match, now, confirmed=True)

        # 0.60-0.89 -> "Did you say Leo?"
        self.pending = match
        self.state = State.CONFIRMING
        return [Confirm(match.word)]

    def on_done(self, now: float) -> list[Action]:
        """Getting words out Done button: end the turn now."""
        return self._end_turn()

    def on_stop(self, now: float = 0.0) -> list[Action]:
        self.state = State.ENDED
        return [Stop()]

    # --- internals ------------------------------------------------------------

    def _found(self, match: Match, now: float, confirmed: bool) -> list[Action]:
        self.state = State.PRAISING
        acts: list[Action] = []
        if not self.logged_this_turn:
            self.logged_this_turn = True
            repeated = self.level == HintLevel.WORD
            outcome = Outcome.REPEATED if repeated else Outcome.FOUND
            seconds = None if self.turn_started_at is None else max(0.0, now - self.turn_started_at)
            acts.append(
                LogAttempt(
                    Attempt(
                        session_id=self.session_id,
                        word_id=match.word.id,
                        hint_level=self.level,
                        outcome=outcome,
                        seconds_to_find=seconds,
                        match_score=match.score,
                        confirmed=confirmed or match.score >= 0.90,
                    )
                )
            )
        acts.append(Praise(match.word))
        return acts

    def _move_on(self, now: float) -> list[Action]:
        acts: list[Action] = []
        if self.target is not None and not self.logged_this_turn:
            self.logged_this_turn = True
            seconds = None if self.turn_started_at is None else max(0.0, now - self.turn_started_at)
            acts.append(
                LogAttempt(
                    Attempt(
                        session_id=self.session_id,
                        word_id=self.target.id,
                        hint_level=self.level,
                        outcome=Outcome.MOVED_ON,
                        seconds_to_find=seconds,
                        match_score=0.0,
                        confirmed=False,
                    )
                )
            )
        self.state = State.SPEAKING
        acts.append(MoveOn())
        return acts

    def _end_turn(self) -> list[Action]:
        self.state = State.SPEAKING
        return [EndTurn()]
