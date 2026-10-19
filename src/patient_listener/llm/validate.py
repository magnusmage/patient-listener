"""The validator: code, runs on every generated line, live or nightly (workbook: AI and
safety -> Validator checks; FR-21, FR-24). Validate, then speak. A rejected line is retried
once with the reason stated, then a template plays - it never reaches the person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..banned import CLINICAL, MEDICAL, NEGATIVE, UNDERSTOOD, profile_pattern
from ..schemas import ReplyFacts

__all__ = ["Verdict", "check_reply", "tokenize", "proper_nouns", "MAX_WORDS"]

MAX_WORDS = 15  # FR-24 / DS-C01 (spoken lines)
REVEAL_THRESHOLD = 0.85  # fuzzy match of a not-yet-found word in the line

_WORD = re.compile(r"[A-Za-z0-9']+")
_SENT_END = re.compile(r"[.!?]$")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""


def _reject(reason: str) -> Verdict:
    return Verdict(ok=False, reason=reason)


def _ok() -> Verdict:
    return Verdict(ok=True)


def tokenize(line: str) -> list[str]:
    return _WORD.findall(line)


def _ratio(a: str, b: str) -> float:
    from ..text.fuzzy import ratio

    return ratio(a.lower(), b.lower()) / 100.0


def _fuzzy_in(word: str, tokens: list[str], threshold: float) -> bool:
    return any(_ratio(word, t) >= threshold for t in tokens)


def proper_nouns(line: str) -> list[str]:
    """Capitalised words that are not sentence-initial (and not 'I'): candidate invented names."""
    out: list[str] = []
    sentence_start = True
    for raw in re.findall(r"[A-Za-z']+|[.!?]", line):
        if raw in ".!?":
            sentence_start = True
            continue
        if raw[0].isupper() and raw != "I" and not sentence_start:
            out.append(raw)
        sentence_start = False
    return out


def check_reply(line: str, facts: ReplyFacts) -> Verdict:
    """Return a :class:`Verdict`. The order mirrors the workbook's validator exactly."""
    tokens = tokenize(line)
    if len(tokens) > MAX_WORDS:
        return _reject("too_long")

    found_lower = {f.lower() for f in facts.found}
    for w in facts.practice_words:
        if w.lower() in found_lower:
            continue
        if int(facts.hint_level) < 3 and _fuzzy_in(w, tokens, REVEAL_THRESHOLD):
            return _reject("reveals_word")  # no early reveal (found words are fine)

    allowed = {n.lower() for n in facts.allowed_names} | {
        n.lower() for n in facts.names_heard_this_turn
    }
    for n in proper_nouns(line):
        if n.lower() not in allowed:
            return _reject("unknown_name")  # no invented people or places

    if profile_pattern(facts.banned_phrases).search(line):
        return _reject("profile_ban")

    if facts.pending_confirm and UNDERSTOOD.search(line):
        return _reject("unconfirmed")  # Being clear: never claim to understand before the tap

    if MEDICAL.search(line) or CLINICAL.search(line):
        return _reject("medical")

    if NEGATIVE.search(line):
        return _reject("negative_feedback")

    return _ok()


def check_meaning_hint(meaning: str, word: str) -> Verdict:
    """Nightly: the meaning line must not contain the word, any part, or a word starting with
    its first two letters (workbook: Nightly hint lines prompt)."""
    tokens = tokenize(meaning)
    w = word.lower()
    first2 = w[:2]
    for t in tokens:
        tl = t.lower()
        if tl == w or (len(first2) == 2 and tl.startswith(first2)):
            return _reject("meaning_reveals_word")
        if _ratio(word, t) >= REVEAL_THRESHOLD:
            return _reject("meaning_reveals_word")
    if len(tokens) > 12:
        return _reject("meaning_too_long")
    return _ok()
