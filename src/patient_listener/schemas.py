"""Typed records that cross every boundary.

Production uses ``pydantic~=2.13`` (D-16) with ``frozen=True, extra="forbid"``. This module
mirrors those schemas with frozen dataclasses plus explicit ``__post_init__`` validation, so
the field limits (``WordEntry.text`` <= 60, ``meaning_cue`` <= 90, ``PlanItem.prompt`` <= 120,
``Plan.items`` <= 10, ...) are enforced with no third-party dependency. A model/record that
fails validation raises ``ValueError`` here exactly as pydantic would, which is why a bad model
reply becomes a template line rather than a half-read string (invariant #2).

Privacy (FR-23, NFR-06): ``Attempt`` holds only a word id, numbers and a timestamp. No field
anywhere carries audio, a transcript or a diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .types import Feedback, HintLevel, Need, Outcome, WordStatus

__all__ = [
    "HintLines",
    "WordEntry",
    "PauseConfig",
    "Attempt",
    "PlanItem",
    "Plan",
    "ReplyFacts",
    "PlanFacts",
    "ValidationError",
]


class ValidationError(ValueError):
    """Raised when a record violates its schema (pydantic-compatible failure)."""


def _max_len(name: str, value: str, limit: int) -> None:
    if len(value) > limit:
        raise ValidationError(f"{name} longer than {limit} characters: {len(value)}")


def _min_len(name: str, value: str, limit: int) -> None:
    if len(value) < limit:
        raise ValidationError(f"{name} shorter than {limit} characters")


def _in_range(name: str, value: Optional[float], lo: float, hi: float) -> None:
    if value is None:
        return
    if not (lo <= value <= hi):
        raise ValidationError(f"{name}={value} outside [{lo}, {hi}]")


WORD_KINDS = frozenset({"person", "place", "food", "object", "activity", "phrase"})
PHRASE_MAX = 60  # FR-63: "my phrases" <= 60 characters


@dataclass(frozen=True)
class HintLines:
    """The three validated hint lines for one word (written nightly)."""

    meaning: str  # <= 90, never contains the word
    sound: str  # "It starts with K."  <= 60
    word: str  # "It's kettle. Say it with me."  <= 60

    def __post_init__(self) -> None:
        _max_len("meaning", self.meaning, 90)
        _max_len("sound", self.sound, 60)
        _max_len("word", self.word, 60)


@dataclass(frozen=True)
class WordEntry:
    """A personal practice word or phrase (FR-40, FR-41, FR-63)."""

    id: str
    person_id: str
    text: str  # 1..60; "Biscuit" or a phrase "Can you open the window?"
    kind: str  # person | place | food | object | activity | phrase
    meaning_cue: str = ""  # <= 90, "Leo's puppy"
    first_sound: str = ""  # <= 4, ARPAbet/first letter
    photo_id: Optional[str] = None
    status: WordStatus = WordStatus.DRAFT
    added_by: str = "carer"  # carer | slt
    approved_by: Optional[str] = None
    hints: Optional[HintLines] = None  # written nightly, validated

    def __post_init__(self) -> None:
        _min_len("text", self.text, 1)
        _max_len("text", self.text, PHRASE_MAX)
        _max_len("meaning_cue", self.meaning_cue, 90)
        _max_len("first_sound", self.first_sound, 4)
        if self.kind not in WORD_KINDS:
            raise ValidationError(f"unknown kind: {self.kind!r}")
        if self.added_by not in ("carer", "slt"):
            raise ValidationError(f"added_by must be carer|slt, got {self.added_by!r}")

    @property
    def is_phrase(self) -> bool:
        return self.kind == "phrase"


# Sentinels for profile merging (see voice/merge.py).
class _Inherit:
    """'This profile has no opinion' -> defer to the others."""

    _instance = None

    def __new__(cls):  # singleton so identity checks work
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "INHERIT"


INHERIT = _Inherit()
NEVER = None  # "this must never happen"


@dataclass(frozen=True)
class PauseConfig:
    """Merged from the person's needs (voice/merge.py). ``None`` means never."""

    needs: frozenset[Need] = field(default_factory=lambda: frozenset({Need.FINDING_WORDS}))
    backchannel_s: Optional[float] = 4.0  # None = never (WORDS_OUT); 2..15
    offer_hint_s: Optional[float] = 7.0  # None = never; settings range 4..15
    max_wait_s: Optional[float] = 20.0  # None = only Done ends the turn (WCAG 2.2.1); 8..120
    needs_complete_text: bool = False  # WORDS_OUT: silence AND complete-sounding text
    hint_order: tuple[HintLevel, ...] = (HintLevel.MEANING, HintLevel.SOUND, HintLevel.WORD)
    max_backchannels_per_turn: int = 2
    allowed_phrases: frozenset[str] = field(
        default_factory=lambda: frozenset({"mm", "take_your_time", "no_rush"})
    )
    banned_phrases: frozenset[str] = field(default_factory=frozenset)
    feedback: frozenset[Feedback] = field(
        default_factory=lambda: frozenset({Feedback.WORD_FOUND})
    )
    max_session_min: Optional[int] = 20  # None = no cap; 3..120
    max_turns: Optional[int] = None  # SAVING_ENERGY: 15
    rest_every_turns: Optional[int] = None  # SAVING_ENERGY: 5
    loudness_floor_db: Optional[float] = None  # BEING_HEARD: baseline - 2 dB

    def __post_init__(self) -> None:
        _in_range("backchannel_s", self.backchannel_s, 2, 15)
        _in_range("offer_hint_s", self.offer_hint_s, 4, 15)
        _in_range("max_wait_s", self.max_wait_s, 8, 120)
        _in_range("max_session_min", self.max_session_min, 3, 120)
        if HintLevel.WORD not in self.hint_order:
            raise ValidationError("hint_order must end with WORD")


@dataclass(frozen=True)
class Attempt:
    """One stored row per target word per turn. No text, no audio (FR-23)."""

    session_id: str
    word_id: str
    hint_level: HintLevel
    outcome: Outcome
    seconds_to_find: Optional[float]
    match_score: float  # matcher confidence, 0..1
    confirmed: bool
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _in_range("match_score", self.match_score, 0.0, 1.0)


@dataclass(frozen=True)
class PlanItem:
    word_id: str
    reason: str  # due | new | returning
    prompt: str  # "Who is this?"  <= 120

    def __post_init__(self) -> None:
        _max_len("prompt", self.prompt, 120)
        if self.reason not in ("due", "new", "returning"):
            raise ValidationError(f"reason must be due|new|returning, got {self.reason!r}")


@dataclass(frozen=True)
class Plan:
    person_id: str
    mode: str
    items: tuple[PlanItem, ...]
    pause: PauseConfig

    def __post_init__(self) -> None:
        if len(self.items) > 10:
            raise ValidationError(f"plan has {len(self.items)} items; max 10")


@dataclass(frozen=True)
class ReplyFacts:
    """Everything sent to Token Factory for a live reply, and nothing else (Definitions)."""

    person_first_name: str
    topic: str
    hint_level: HintLevel
    practice_words: tuple[str, ...]
    found: tuple[str, ...]
    last_words_heard: str  # <= 20 words
    needs: frozenset[Need]
    allowed_names: frozenset[str] = field(default_factory=frozenset)
    names_heard_this_turn: frozenset[str] = field(default_factory=frozenset)
    pending_confirm: bool = False
    banned_phrases: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PlanFacts:
    """Nightly fact record for one word."""

    word: str
    kind: str
    meaning_cue: str
    first_letter: str
