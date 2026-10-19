"""Enums and value types that cross every boundary (workbook: Developer guide -> Data types).

These never carry a diagnosis. ``Need`` is what the person says is hard, chosen on P0.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

__all__ = [
    "HintLevel",
    "Outcome",
    "State",
    "Mode",
    "WordStatus",
    "Need",
    "Feedback",
]


class HintLevel(IntEnum):
    NONE = 0  # found without help
    MEANING = 1  # "You boil water in it."
    SOUND = 2  # "It starts with K."
    WORD = 3  # "It's kettle. Say it with me."


class Outcome(StrEnum):
    FOUND = "found"  # said it (any hint level before WORD)
    REPEATED = "repeated"  # said it after hearing it (WORD level)
    MOVED_ON = "moved_on"  # person or controller moved on
    UNSURE = "unsure"  # heard something close, not confirmed


class State(StrEnum):
    GREETING = "greeting"
    LISTENING = "listening"
    SILENT = "silent"
    BACKCHANNELED = "backchanneled"
    HINT_OFFERED = "hint_offered"
    HINTING = "hinting"
    CONFIRMING = "confirming"
    PRAISING = "praising"
    SPEAKING = "speaking"
    SAFETY_STOP = "safety_stop"
    ENDED = "ended"


class Mode(StrEnum):
    PICTURE = "picture"
    CHAT = "chat"
    REVIEW = "review"
    SHORT = "short"
    SCRIPT = "script"


class WordStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class Need(StrEnum):
    """Chosen by the person on P0; never a diagnosis."""

    FINDING_WORDS = "finding_words"  # aphasia, PPA, brain injury, long COVID
    WORDS_OUT = "words_out"  # stammering, cluttering, apraxia
    BEING_HEARD = "being_heard"  # quiet voice (Parkinson's)
    BEING_CLEAR = "being_clear"  # dysarthria, atypical speech
    SAVING_ENERGY = "saving_energy"  # MND, MS, long COVID, fatigue
    LISTENING = "listening"  # hearing loss / cochlear implant (later)


class Feedback(StrEnum):
    WORD_FOUND = "word_found"
    LOUDNESS = "loudness"
    WHAT_I_HEARD = "what_i_heard"
    TIME_USED = "time_used"
