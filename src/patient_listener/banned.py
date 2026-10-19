"""The single banned-word list, shared by the UI copy lint and the reply validator.

Workbook: "Banned-word list (DS-C03, C04, C05) shared by the UI copy lint and the reply
validator: one file, ``src/patient_listener/banned.py``." Keeping both in one place means the
words the app must never *show* and the words a model reply must never *contain* can never
drift apart.
"""

from __future__ import annotations

import re

from .types import Need

__all__ = [
    "NEGATIVE",
    "CLINICAL",
    "MEDICAL",
    "UNDERSTOOD",
    "profile_pattern",
    "PROFILE_BANNED_WORDS",
]


def _words(*terms: str) -> re.Pattern[str]:
    """Case-insensitive pattern matching any term on word boundaries."""
    alt = "|".join(re.escape(t) for t in terms)
    return re.compile(rf"(?<![\w-])(?:{alt})(?![\w-])", re.IGNORECASE)


# DS-C03: never make practice feel like a test.
NEGATIVE = re.compile(
    r"(?<![\w-])(?:wrong|incorrect|try again|oops|failed|fail|score|level up|streak|"
    r"well done!!)(?![\w-])|!!",
    re.IGNORECASE,
)

# DS-C04 + claims table: never clinical/therapy claims.
CLINICAL = _words(
    "therapy",
    "treatment",
    "treat",
    "rehabilitation",
    "rehabilitate",
    "recovery",
    "recover",
    "decline",
    "severity",
    "severe",
    "diagnose",
    "diagnosis",
    "clinically proven",
)

# Medical-advice content (no medication/symptom/prognosis advice).
MEDICAL = _words(
    "medication",
    "medicine",
    "dose",
    "dosage",
    "prescribe",
    "prescription",
    "symptom",
    "symptoms",
    "prognosis",
    "stroke",
    "aphasia",
    "dysarthria",
    "parkinson",
    "diagnose",
    "diagnosis",
    "therapy",
    "treatment",
)

# Being clear: never claim understanding before the person confirms.
UNDERSTOOD = _words(
    "i understood",
    "i understand",
    "understood",
    "i got that",
    "i heard you clearly",
    "got it",
)

# DS-C05 (+ merged PauseConfig.banned_phrases). Stored as single tokens with underscores;
# matched here on word boundaries with the underscore read as a space.
PROFILE_BANNED_WORDS: dict[str, tuple[str, ...]] = {
    "slow": ("slow", "slow down"),
    "relax": ("relax",),
    "breathe": ("breathe", "breath", "take a breath"),
    "calm": ("calm", "calm down"),
    "take_your_time": ("take your time",),
    "no_rush": ("no rush",),
    "shout": ("shout", "shouting", "louder!"),
    "db_number": ("decibel", "decibels", "db", "dbfs"),
    "one_more": ("one more",),
}


def profile_pattern(banned_phrases: frozenset[str]) -> re.Pattern[str]:
    """Compile a pattern for the merged ``PauseConfig.banned_phrases`` of a session."""
    terms: list[str] = []
    for token in banned_phrases:
        terms.extend(PROFILE_BANNED_WORDS.get(token, (token.replace("_", " "),)))
    if not terms:
        return re.compile(r"(?!x)x")  # matches nothing
    return _words(*terms)
