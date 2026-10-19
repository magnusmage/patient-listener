"""Safety phrase rules (workbook: AI and safety -> Guardrails; FR-80, FR-81, FR-82, FR-83).

Rules first, never a model to decide a stop ("a miss here matters most; rules don't drift").
A ``SafetySignal`` is returned on the person's speech, a typed line, or a carer message. The
card wording and the local emergency number are chosen by the UI layer. Practice data is never
inspected for a health change (FR-83): this module reads only the text in front of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["SafetyKind", "SafetySignal", "check", "emergency_number"]


class SafetyKind(StrEnum):
    STROKE = "stroke_signs"
    DISTRESS = "distress"
    RED_FLAG_HOARSE = "red_flag:hoarse"
    RED_FLAG_NEW_STAMMER = "red_flag:new_stammer"
    RED_FLAG_CHOKING = "red_flag:choking"
    RED_FLAG_BREATHLESS = "red_flag:breathless"
    RED_FLAG_HEARING = "red_flag:hearing"


@dataclass(frozen=True)
class SafetySignal:
    kind: SafetyKind
    card: str  # the card id the UI shows (== kind value)
    pause_loudness: bool = False  # FR-82: hoarseness pauses loudness practice


_EMERGENCY = {"UK": "999", "US": "911", "PK": "1122"}


def emergency_number(region: str = "UK") -> str:
    return _EMERGENCY.get(region.upper(), "your local emergency number")


# --- Stroke signs (FR-80): broad phrasings; call even if symptoms pass. ---
_STROKE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\barm\b.*\b(weak|funny|numb|droop|heavy|won'?t move|can'?t move)\b", re.I),
    re.compile(r"\b(weak|funny|numb|droop|heavy)\b.*\barm\b", re.I),
    re.compile(r"\bface\b.*\b(droop|drooping|droopy|numb|falling|slipping)\b", re.I),
    re.compile(r"\b(droop|drooping|droopy)\b.*\bface\b", re.I),
    re.compile(r"\b(words|speech|talking|voice)\b.*\b(worse|gone|harder)\b.*\b(today|now|suddenly)\b", re.I),
    re.compile(r"\b(suddenly|today|now)\b.*\b(words|speech)\b.*\b(worse|gone|harder)\b", re.I),
    re.compile(r"can'?t (speak|talk) (like )?(yesterday|before)", re.I),
    re.compile(r"\b(speech|words)\b.*\bsuddenly\b.*\b(worse|different|gone)\b", re.I),
    re.compile(r"\bwords\b.*\bworse\b", re.I),
)

# --- Distress (FR-81): includes short non-fluent phrases. ---
_DISTRESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bi'?m useless\b", re.I),
    re.compile(r"\bwhat'?s the point\b", re.I),
    re.compile(r"\bno\W+point\b", re.I),  # "no... point..."
    re.compile(r"\bpoint\W+me\b", re.I),  # "no... point... me"
    re.compile(r"\bgive up\b", re.I),
    re.compile(r"\bkill (my ?self|me)\b", re.I),
    re.compile(r"\b(end|hurt) (it all|my ?self)\b", re.I),
    re.compile(r"\bcan'?t go on\b", re.I),
    re.compile(r"\bhopeless\b", re.I),
)

# --- Profile red flags (FR-82): usually setup answers; also catch in-session mentions. ---
_RED_FLAGS: tuple[tuple[re.Pattern[str], SafetyKind, bool], ...] = (
    (re.compile(r"\bhoarse\b.*\b(3|three|4|four)\+?\s*weeks?\b", re.I), SafetyKind.RED_FLAG_HOARSE, True),
    (re.compile(r"\b(voice|throat)\b.*\bhoarse\b.*\bweeks?\b", re.I), SafetyKind.RED_FLAG_HOARSE, True),
    (re.compile(r"\bnew\b.*\bstammer\b", re.I), SafetyKind.RED_FLAG_NEW_STAMMER, False),
    (re.compile(r"\bstammer\b.*\b(started|recently|new)\b", re.I), SafetyKind.RED_FLAG_NEW_STAMMER, False),
    (re.compile(r"\bchok(e|ing)\b.*\b(drink|water|eat|swallow)\b", re.I), SafetyKind.RED_FLAG_CHOKING, False),
    (re.compile(r"\bbreathless\b", re.I), SafetyKind.RED_FLAG_BREATHLESS, False),
    (re.compile(r"\b(can'?t|hard to) breathe\b.*\b(talk|speak)\b", re.I), SafetyKind.RED_FLAG_BREATHLESS, False),
    (re.compile(r"\bsudden(ly)?\b.*\bhearing\b", re.I), SafetyKind.RED_FLAG_HEARING, False),
    (re.compile(r"\bhearing\b.*\bsudden(ly)?\b", re.I), SafetyKind.RED_FLAG_HEARING, False),
)


def check(text: str) -> SafetySignal | None:
    """Return the highest-priority safety signal for ``text``, or ``None``.

    Priority: stroke signs first (most time-critical), then distress, then profile red flags.
    """
    if not text or not text.strip():
        return None
    low = text.strip()

    for pat in _STROKE_PATTERNS:
        if pat.search(low):
            return SafetySignal(SafetyKind.STROKE, SafetyKind.STROKE.value)

    for pat in _DISTRESS_PATTERNS:
        if pat.search(low):
            return SafetySignal(SafetyKind.DISTRESS, SafetyKind.DISTRESS.value)

    for pat, kind, pause in _RED_FLAGS:
        if pat.search(low):
            return SafetySignal(kind, kind.value, pause_loudness=pause)

    return None
