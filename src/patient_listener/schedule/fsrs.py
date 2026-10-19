"""Spaced retrieval (workbook: Best practices -> Scheduling words with FSRS; D-13).

Production pins ``fsrs~=6.3`` and uses ``Scheduler``/``Card``/``Rating`` directly. The *mapping*
from a turn outcome to a rating (the part specific to Patient Listener) is reproduced here
verbatim, and :class:`Scheduler` is a dependency-free stand-in that honours the two contracts
the rest of the system relies on:

* the next due time moves out further the better the recall (least-retrievable-first ordering),
* ``due_tonight`` returns at most ``k`` words.

The interval model here is a simple, monotonic SM-2-style curve, clearly marked as a stand-in;
swapping in the real ``fsrs`` scheduler changes only the numbers inside a card, not the mapping
or the selection contract. ``retention`` and ``maximum_interval`` match the config.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum

from ..types import HintLevel, Outcome

__all__ = ["Rating", "Card", "Scheduler", "to_rating"]


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


def to_rating(outcome: Outcome, level: HintLevel, seconds: float) -> Rating:
    """Map a turn outcome to an FSRS rating (workbook table, verbatim)."""
    if outcome is Outcome.FOUND and level is HintLevel.NONE:
        return Rating.EASY if seconds < 4 else Rating.GOOD
    if outcome is Outcome.FOUND:  # after the meaning or sound hint
        return Rating.HARD
    return Rating.AGAIN  # REPEATED (needed the word), MOVED_ON, UNSURE


@dataclass
class Card:
    stability: float = 0.0  # days
    difficulty: float = 5.0  # 1..10
    reps: int = 0
    due: str = ""  # ISO 8601 UTC; "" means due now (new card)
    last_review: str = ""

    @classmethod
    def new(cls) -> "Card":
        return cls()

    @classmethod
    def from_json(cls, s: str) -> "Card":
        return cls(**json.loads(s))

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def due_dt(self) -> datetime:
        if not self.due:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        return datetime.fromisoformat(self.due)


class Scheduler:
    def __init__(self, desired_retention: float = 0.85, maximum_interval: int = 60) -> None:
        self.desired_retention = desired_retention
        self.maximum_interval = maximum_interval

    def review_card(
        self, card: Card, rating: Rating, now: datetime | None = None
    ) -> Card:
        now = now or datetime.now(timezone.utc)
        reps = card.reps + 1
        diff = min(10.0, max(1.0, card.difficulty + (3 - int(rating)) * 0.6))

        if rating is Rating.AGAIN:
            stability = max(0.25, card.stability * 0.3) if card.stability else 0.5
        else:
            base = card.stability if card.stability else 1.0
            mult = {Rating.HARD: 1.4, Rating.GOOD: 2.2, Rating.EASY: 3.2}[rating]
            # Lower desired retention => slightly longer intervals (shorter sessions).
            retention_boost = 1.0 + (0.9 - self.desired_retention)
            stability = min(float(self.maximum_interval), base * mult * retention_boost)

        interval_days = min(float(self.maximum_interval), max(0.25, stability))
        due = now + timedelta(days=interval_days)
        return Card(
            stability=stability,
            difficulty=diff,
            reps=reps,
            due=due.isoformat(),
            last_review=now.isoformat(),
        )

    def retrievability(self, card: Card, now: datetime | None = None) -> float:
        """Rough probability of recall now; lower => more urgent (ordering key)."""
        now = now or datetime.now(timezone.utc)
        if not card.last_review or card.stability <= 0:
            return 0.0  # new cards are the most urgent
        elapsed = (now - datetime.fromisoformat(card.last_review)).total_seconds() / 86400.0
        import math

        return math.exp(-elapsed / max(0.1, card.stability))


def due_tonight(cards: dict[str, str], k: int = 10, now: datetime | None = None) -> list[str]:
    """Return up to ``k`` due word ids, least retrievable first (workbook ``due_tonight``)."""
    now = now or datetime.now(timezone.utc)
    sched = Scheduler()
    parsed = {w: Card.from_json(j) for w, j in cards.items()}
    due = {w: c for w, c in parsed.items() if c.due_dt() <= now}
    return sorted(due, key=lambda w: sched.retrievability(due[w], now))[:k]
