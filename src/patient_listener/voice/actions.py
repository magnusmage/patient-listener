"""Actions the patience controller returns. The pipeline executes them; the controller
never performs I/O itself (invariant #1)."""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import Attempt, WordEntry
from ..types import HintLevel

__all__ = [
    "Action",
    "Play",
    "ShowHint",
    "CheckComplete",
    "MoveOn",
    "EndTurn",
    "Confirm",
    "Praise",
    "LogAttempt",
    "Speak",
    "SafetyStop",
    "Stop",
    "OfferRest",
]


class Action:
    """Base class for everything the controller can ask the pipeline to do."""


@dataclass(frozen=True)
class Play(Action):
    """Play a pre-rendered cached clip by key ('mm', 'offer_hint', 'yes', 'hint:<id>:<lvl>')."""

    key: str


@dataclass(frozen=True)
class ShowHint(Action):
    word: WordEntry
    level: HintLevel


@dataclass(frozen=True)
class CheckComplete(Action):
    """Getting words out: ask Lightning whether the transcript reads as complete (1.0 s budget)."""


@dataclass(frozen=True)
class MoveOn(Action):
    """A kind 'let's try another' when the wait limit passes with no answer."""


@dataclass(frozen=True)
class EndTurn(Action):
    """Hand the turn to the reply step."""


@dataclass(frozen=True)
class Confirm(Action):
    """Ask 'Did you say Leo?' for a 0.60-0.89 match."""

    word: WordEntry


@dataclass(frozen=True)
class Praise(Action):
    """A quiet 'Yes, Leo.' after a confirmed find."""

    word: WordEntry


@dataclass(frozen=True)
class LogAttempt(Action):
    attempt: Attempt


@dataclass(frozen=True)
class Speak(Action):
    """A live reply line (validated before it is spoken) or a template line."""

    text: str


@dataclass(frozen=True)
class SafetyStop(Action):
    card: str  # 'stroke_signs' | 'distress' | 'red_flag:<...>'


@dataclass(frozen=True)
class Stop(Action):
    """End the session (Stop button, 'stop', or plan done)."""


@dataclass(frozen=True)
class OfferRest(Action):
    """Saving energy: 'Rest?' every N turns."""
