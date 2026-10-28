"""Pure presentation helpers: turn core value types into the dicts the frontend renders.

No I/O and no state - every function is a pure mapping, so it is unit-testable in isolation and
carries none of the controller's decision logic. The controller still decides *what* happens;
this module only decides how to *describe* it to ``web/app.js``.
"""

from __future__ import annotations

import re

from .word_emoji import KIND_EMOJI, word_emoji
from ..schemas import WordEntry
from ..types import Feedback
from ..voice import safety as safetymod

__all__ = [
    "KIND_EMOJI",
    "prompt_payload",
    "feedback_key",
    "safety_card",
    "close_variant",
    "STROKE_PHRASE",
]

STROKE_PHRASE = "my arm feels funny and words are worse today"

# Curated near-misses that land in the matcher's 0.60-0.89 "confirm" band for the seeded demo
# words, so the "say a close word" demo control reliably exercises the confirm step. Unknown
# words fall back to :func:`_generic_close`.
_CLOSE = {
    "Leo": "Lea",
    "Biscuit": "Biscaa",
    "kettle": "kentle",
    "Whitby": "Whitbee",
    "good morning": "good mornan",
    "the garden": "the garda",
}


def feedback_key(feedback: frozenset[Feedback]) -> str:
    """The single feedback mode the frontend switches its P3b panel on."""
    for f in (Feedback.LOUDNESS, Feedback.WHAT_I_HEARD, Feedback.TIME_USED, Feedback.WORD_FOUND):
        if f in feedback:
            return f.value
    return Feedback.WORD_FOUND.value


def prompt_payload(word: WordEntry | None, feedback: frozenset[Feedback], profile: str) -> dict:
    """The ``prompt`` event body: topic, placeholder photo, lead line, profile, feedback mode."""
    fb = feedback_key(feedback)
    if word is None or not word.text:
        # Getting words started: an open prompt, no target word.
        return {
            "topic": "tell me about your day",
            "photo": "🗓️",
            "text": "Go ahead when you are ready.",
            "profile": profile,
            "feedback": fb,
        }
    emoji = word_emoji(word.text, word.kind)
    topic = f"photo: {word.meaning_cue}" if word.meaning_cue else "Look at the picture."
    lead = "Say it when you are ready." if fb != "word_found" else "What is this?"
    return {
        "topic": topic,
        "photo": emoji,
        "text": lead,
        "profile": profile,
        "feedback": fb,
    }


def safety_card(card: str, region: str = "UK") -> dict:
    """The ``safety`` event body for a safety-stop card id (card ids are ``SafetyKind`` values)."""
    number = safetymod.emergency_number(region)
    if card == safetymod.SafetyKind.STROKE.value:
        return {
            "card": card,
            "title": f"Call {number} now",
            "body": "Sudden changes in speech, face or arm need help now.",
            "number": number,
        }
    if card == safetymod.SafetyKind.DISTRESS.value:
        return {
            "card": card,
            "title": "You are not alone",
            "body": "If you are struggling, you can call Samaritans on 116 123.",
            "number": "116 123",
        }
    # Profile red flags: a calm prompt to talk to a clinician, no emergency number.
    return {
        "card": card,
        "title": "Worth mentioning",
        "body": "This is one to talk to your doctor or speech therapist about.",
        "number": None,
    }


def _generic_close(text: str) -> str:
    """A plausible near-miss for an unknown word: keep the onset, blur the tail."""
    half = max(1, len(text) // 2 + 1)
    head, tail = text[:half], text[half:]
    tail = re.sub(r"[aeiouAEIOU]", "a", tail)
    tail = tail[:-1] if len(tail) > 1 else tail
    return head + tail or text


def close_variant(text: str) -> str:
    """A near-miss of ``text`` for the 'say a close word' demo control."""
    return _CLOSE.get(text, _generic_close(text))
