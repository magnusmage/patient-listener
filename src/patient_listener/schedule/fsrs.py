"""Workbook D-13: real FSRS 6.3.2, with compatibility for saved prototype cards."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum

from fsrs import Card as FsrsCard, Rating as FsrsRating, Scheduler as FsrsScheduler
from ..types import HintLevel, Outcome


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


def utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Review timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def to_rating(outcome: Outcome, level: HintLevel, seconds: float | None) -> Rating:
    if outcome is Outcome.FOUND and level is HintLevel.NONE:
        return Rating.EASY if seconds is not None and seconds < 4 else Rating.GOOD
    if outcome is Outcome.FOUND:
        return Rating.HARD
    return Rating.AGAIN


@dataclass
class Card:
    native: FsrsCard
    legacy: dict | None = None

    @classmethod
    def new(cls) -> Card:
        # New cards are due even when selecting at an explicitly supplied past time.
        return cls(FsrsCard(due=datetime(1970, 1, 1, tzinfo=timezone.utc)))

    @classmethod
    def from_json(cls, value: str) -> Card:
        data = json.loads(value)
        if "card_id" not in data:
            # Stand-in difficulty/stability are not valid FSRS model estimates.
            # The store replays saved attempts on startup; keep the original as provenance.
            if set(data) != {"stability", "difficulty", "reps", "due", "last_review"}:
                raise ValueError("Unknown scheduling card format")
            result = cls.new()
            result.legacy = data
            return result
        return cls(FsrsCard.from_json(value), data.get("_legacy"))

    def to_json(self) -> str:
        data = json.loads(self.native.to_json())
        if self.legacy is not None:
            data["_legacy"] = self.legacy
        return json.dumps(data)

    def due_dt(self) -> datetime:
        return utc(self.native.due)


class Scheduler:
    def __init__(self, desired_retention: float = 0.85, maximum_interval: int = 60,
                 *, enable_fuzzing: bool = True) -> None:
        self.native = FsrsScheduler(desired_retention=desired_retention,
                                    maximum_interval=maximum_interval,
                                    enable_fuzzing=enable_fuzzing)

    def review_card(self, card: Card, rating: Rating, now: datetime | None = None) -> Card:
        reviewed, _log = self.native.review_card(
            card.native, FsrsRating(int(rating)), review_datetime=utc(now))
        return Card(reviewed, card.legacy)

    def retrievability(self, card: Card, now: datetime | None = None) -> float:
        return self.native.get_card_retrievability(card.native, current_datetime=utc(now))


def due_tonight(cards: dict[str, str], k: int = 10, now: datetime | None = None) -> list[str]:
    if type(k) is not int or k < 0:
        raise ValueError("Word limit must be a nonnegative integer")
    now = utc(now)
    sched = Scheduler()
    parsed = {word: Card.from_json(value) for word, value in cards.items()}
    due = {word: card for word, card in parsed.items() if card.due_dt() <= now}
    return sorted(due, key=lambda word: sched.retrievability(due[word], now))[:min(k, 10)]
