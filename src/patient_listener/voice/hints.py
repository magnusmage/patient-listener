"""The hint ladder (workbook: AI and safety -> The hint ladder; FR-20, FR-21, FR-41).

Level 0 none, 1 meaning (Super overnight), 2 sound (code from ``first_sound``), 3 word
(template; logged ``repeated``). The order adapts per person (``hint_order``); the meaning
line must never contain the word (enforced nightly by the validator). This module only *picks*
and *renders* the ladder; it never generates text live.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import HintLines, WordEntry
from ..types import HintLevel

__all__ = ["HintStep", "sound_line", "word_line", "template_hint_lines", "next_level", "render"]


@dataclass(frozen=True)
class HintStep:
    level: HintLevel
    text: str
    clip_key: str


def sound_line(first_sound: str) -> str:
    """Level-2 template: 'It starts with K.'"""
    return f"It starts with {first_sound.upper()}."


def word_line(word: str) -> str:
    """Level-3 template: 'It's kettle. Say it with me: kettle.'"""
    return f"It's {word}. Say it with me: {word}."


def template_hint_lines(word: WordEntry, meaning: str | None = None) -> HintLines:
    """Build the three lines. ``meaning`` comes from Super; a safe template is used if absent."""
    safe_meaning = meaning or (word.meaning_cue or f"Think about {word.kind}.")
    # Never let the template meaning contain the word (belt-and-braces; the validator also checks).
    if word.text.lower() in safe_meaning.lower():
        safe_meaning = f"Think about {word.kind}."
    return HintLines(
        meaning=safe_meaning[:90],
        sound=sound_line(word.first_sound or word.text[:1]),
        word=word_line(word.text),
    )


def next_level(current: HintLevel, order: tuple[HintLevel, ...]) -> HintLevel:
    """The next hint level in ``order`` (never past the last)."""
    if current in order:
        i = order.index(current) + 1
    else:
        i = 0
    return order[min(i, len(order) - 1)]


def render(word: WordEntry, level: HintLevel) -> HintStep:
    """Render one hint step; falls back to templates if ``word.hints`` is missing."""
    hints = word.hints or template_hint_lines(word)
    if level == HintLevel.MEANING:
        text = hints.meaning
    elif level == HintLevel.SOUND:
        text = hints.sound
    else:
        text = hints.word
    return HintStep(level=level, text=text, clip_key=f"hint:{word.id}:{int(level)}")
