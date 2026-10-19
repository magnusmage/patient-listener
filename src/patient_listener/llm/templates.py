"""Template lines (workbook: Definitions -> Template line). A fixed, pre-written line used
whenever a model is late, fails validation twice, or AI is switched off (FR-84). Every template
already satisfies the validator by construction.
"""

from __future__ import annotations

from ..schemas import ReplyFacts

__all__ = [
    "greeting",
    "reply_template",
    "weekly_card_template",
    "progress_summary_template",
    "safety_line",
    "MEDICAL_REDIRECT",
]

MEDICAL_REDIRECT = "That's one for your doctor or therapist."


def greeting(first_name: str) -> str:
    return f"Hi {first_name}. I'm an AI practice partner. Shall we look at a photo?"


def reply_template(facts: ReplyFacts) -> str:
    """A safe next line that reveals no not-yet-found word and invents no name."""
    if facts.found and facts.found[-1].lower() in {f.lower() for f in facts.found}:
        # A word was just found: move the conversation on without naming anything new.
        return "Lovely. Tell me more."
    if facts.topic.startswith("photo"):
        return "Take your time. What else can you see?"
    return "Thanks. What else would you like to say?"


def safety_line(local_number: str) -> str:
    return (
        f"If speech, face or arm change suddenly, call {local_number}. "
        "For slower changes, talk to your doctor or speech therapist."
    )


def weekly_card_template(name: str, found_no_hint: int, new_words: list[str], local_number: str) -> str:
    new = ", ".join(new_words) if new_words else "none"
    return (
        f"{found_no_hint} practice words found without a hint this week. New: {new}. "
        + safety_line(local_number)
    )


def progress_summary_template(found_no_hint: int, found_with_hint: int) -> str:
    return (
        f"This week: {found_no_hint} words found without a hint, {found_with_hint} after a hint. "
        "I can't say how her speech or health is; her SLT or doctor can."
    )
