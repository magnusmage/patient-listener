"""Word matcher (FR-22, DR-4). A model NEVER decides success; this code plus a confirm step
does (workbook: AI and safety -> Who does what).

``score = max(spelling, 0.6*spelling + 0.4*sound)`` where ``spelling`` is the rapidfuzz ratio
/100 and ``sound`` is 1 if the Metaphone codes match. Bands:

* ``>= 0.90`` -> found (log it),
* ``0.60-0.89`` -> confirm ("Did you say Leo?"),
* ``< 0.60``   -> treated as speech, not a match.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import WordEntry
from ..text.fuzzy import ratio
from ..text.phonetics import metaphone

__all__ = ["Match", "score", "best_match", "FOUND_THRESHOLD", "CONFIRM_THRESHOLD"]

FOUND_THRESHOLD = 0.90  # FR-22 / Definitions; G-04 may raise the log threshold to 0.95
CONFIRM_THRESHOLD = 0.60


@dataclass(frozen=True)
class Match:
    word: WordEntry
    score: float

    @property
    def is_found(self) -> bool:
        return self.score >= FOUND_THRESHOLD

    @property
    def needs_confirm(self) -> bool:
        return CONFIRM_THRESHOLD <= self.score < FOUND_THRESHOLD


def _dedupe_repeats(tokens: list[str]) -> list[str]:
    """Collapse runaway repeats the ASR can emit ('the the the')."""
    out: list[str] = []
    for t in tokens:
        if not out or out[-1].lower() != t.lower():
            out.append(t)
    return out


def score(heard: str, target: str) -> float:
    """The FR-22 match score for a single heard phrase against a single target."""
    h = heard.lower().replace(" ", "")
    t = target.lower().replace(" ", "")
    spelling = ratio(h, t) / 100.0
    sound = 1.0 if metaphone(h) == metaphone(t) else 0.0
    return max(spelling, 0.6 * spelling + 0.4 * sound)


def best_match(heard: list[str], words: list[WordEntry]) -> Match | None:
    """Best (highest-scoring) list word for what was heard, or ``None`` below 0.60.

    Scores each list word against (a) the full heard phrase and (b) every heard token, taking
    the max, so "Whit... Whitby!" matches on "Whitby" and "my grandson is Leo" matches on "Leo".
    """
    if not words:
        return None
    tokens = _dedupe_repeats([t for t in heard if t.strip()])
    phrase = " ".join(tokens)
    best: Match | None = None
    for w in words:
        candidates = [score(phrase, w.text)] + [score(tok, w.text) for tok in tokens]
        s = max(candidates) if candidates else 0.0
        if s >= CONFIRM_THRESHOLD and (best is None or s > best.score):
            best = Match(word=w, score=s)
    return best
