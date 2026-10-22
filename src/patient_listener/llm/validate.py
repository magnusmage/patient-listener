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


# Conservative lexical grounding for short practice replies. Content outside these
# conversational words must occur in the supplied facts; this is not a semantic proof.
_CONVERSATION_WORDS = frozenset("""
a an the i i'm i've i'd i'll me my mine we we're we've we'd we'll us our ours
 you you're you've you'd you'll your yours it it's its this that that's these those
 he he's his him she she's her hers they they're them their theirs
 is isn't are aren't was wasn't were weren't be been being am do don't does doesn't
 did didn't doing have haven't has hasn't had hadn't can can't could couldn't
 would wouldn't will won't shall should shouldn't may might must
 and or but if then so because as at by for from in into of on to with without
 about after before again also all any each every just more much many some same
 else other another now next today here there where when what what's which who who's
 how why yes okay ok thanks thank lovely nice good well done
 tell say said saying talk talking share describe ask asked question answer
 want wants wanted like likes liked would let let's try trying practice practising
 time take keep go going get got something anything everything nothing
 see photo picture look word words sound sounds start started finish finished
 help please together little bit once repeat ready welcome
""".split())
_UNSUPPORTED_CLAIM = re.compile(
    r"\b(?:you|he|she|they)\s+(?:look|looks|looked|seem|seems|seemed|sound|sounds|sounded)\b"
    r"|\b(?:your|his|her|their)\s+(?:face|appearance|body|voice)\b"
    r"|\b(?:i|we)\s+(?:(?:can|could)\s+)?(?:see|hear|saw|heard|watch|watching)\b",
    re.I,
)


def _grounded(line: str, tokens: list[str], facts: ReplyFacts) -> bool:
    context = " ".join((facts.last_words_heard, facts.topic, facts.person_first_name,
                        *facts.found, *facts.allowed_names, *facts.names_heard_this_turn))
    allowed = _CONVERSATION_WORDS | {t.lower() for t in tokenize(context)}
    # Word-level hints may name a practice word, but do not license new facts.
    if int(facts.hint_level) >= 3:
        allowed |= {t.lower() for w in facts.practice_words for t in tokenize(w)}
    return bool(tokens) and all(t.lower() in allowed for t in tokens)


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

    if _UNSUPPORTED_CLAIM.search(line):
        return _reject("unsupported_claim")
    if not _grounded(line, tokens, facts):
        return _reject("ungrounded_content")

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
