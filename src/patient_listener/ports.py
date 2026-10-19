"""Ports: the Protocols the pure core depends on.

Workbook invariant #3 (Ports and adapters): the core depends on these Protocols; NeMo, Magpie,
Token Factory and the database live in adapters. Tests inject fakes (a ``FakeClock``, a template
``Llm``, an in-memory ``Store``), so no core test needs a GPU, a network or a model.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from .schemas import Attempt, Plan, PlanFacts, ReplyFacts, WordEntry
from .types import Need

__all__ = ["Heard", "Asr", "Tts", "Llm", "Store", "Clock"]


class Heard(Protocol):
    """A word the ASR emitted, with its start/end in seconds."""

    word: str
    start: float
    end: float


@runtime_checkable
class Asr(Protocol):
    async def stream(self, frames: Iterable[bytes]) -> Iterable[Heard]:  # words + timings
        ...


@runtime_checkable
class Tts(Protocol):
    async def speak(self, text: str, voice: str) -> Iterable[bytes]: ...

    def clip(self, key: str) -> Optional[bytes]:  # pre-rendered audio by key
        ...


@runtime_checkable
class Llm(Protocol):
    async def reply(self, facts: ReplyFacts, timeout_s: float) -> Optional[str]:
        """One validated line, or ``None`` to fall back to a template."""
        ...

    async def plan(self, facts: PlanFacts) -> Optional[str]: ...

    async def is_complete(self, question: str, transcript: str, timeout_s: float) -> bool:
        """Getting words out: does the transcript read as a finished thought?"""
        ...


@runtime_checkable
class Store(Protocol):
    def load_plan(self, person_id: str) -> Plan: ...

    def words(self, person_id: str) -> list[WordEntry]: ...

    def log_attempt(self, attempt: Attempt) -> None: ...

    def is_ai_enabled(self) -> bool:  # kill switch (FR-84), read on every model call
        ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float: ...  # FakeClock in tests


def needs_complete_text(needs: frozenset[Need]) -> bool:
    return Need.WORDS_OUT in needs
