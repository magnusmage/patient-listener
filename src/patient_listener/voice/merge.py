"""Profile merging (workbook: Speech difficulties -> Merging; FR-11).

Each profile is a partial :class:`PauseConfig`. A field is a number, ``NEVER`` (None) or
``INHERIT``. Merging follows three rules, verbatim:

* any "never" wins,
* the most patient (longest) wait wins,
* any limit wins (the smallest cap).
"""

from __future__ import annotations

from typing import Any

from ..schemas import INHERIT, NEVER, PauseConfig
from ..types import Feedback, Need

__all__ = ["PROFILES", "merge"]


PROFILES: dict[Need, dict[str, Any]] = {
    Need.FINDING_WORDS: dict(
        backchannel_s=4,
        offer_hint_s=7,
        max_wait_s=20,
        allowed_phrases={"mm", "take_your_time", "no_rush"},
        feedback={Feedback.WORD_FOUND},
        max_session_min=20,
    ),
    Need.WORDS_OUT: dict(
        backchannel_s=NEVER,
        offer_hint_s=NEVER,
        max_wait_s=8,
        needs_complete_text=True,
        allowed_phrases=set(),
        banned_phrases={"slow", "relax", "breathe", "calm", "take_your_time", "no_rush"},
        max_session_min=20,
    ),
    Need.BEING_HEARD: dict(
        backchannel_s=4,
        offer_hint_s=INHERIT,
        max_wait_s=12,
        allowed_phrases={"mm", "a_bit_stronger"},
        banned_phrases={"shout", "db_number"},
        feedback={Feedback.LOUDNESS},
        max_session_min=20,
    ),
    Need.BEING_CLEAR: dict(
        backchannel_s=5,
        offer_hint_s=INHERIT,
        max_wait_s=12,
        allowed_phrases={"mm", "what_i_heard"},
        feedback={Feedback.WHAT_I_HEARD},
        max_session_min=15,
    ),
    Need.SAVING_ENERGY: dict(
        backchannel_s=5,
        offer_hint_s=INHERIT,
        max_wait_s=20,  # 20 s if chosen alone
        allowed_phrases={"mm", "want_a_rest"},
        banned_phrases={"one_more"},
        feedback={Feedback.TIME_USED},
        max_session_min=10,
        max_turns=15,
        rest_every_turns=5,
    ),
    Need.LISTENING: dict(  # later; captions always, natural pace
        backchannel_s=INHERIT,
        offer_hint_s=INHERIT,
        max_wait_s=INHERIT,
        allowed_phrases=set(),
        max_session_min=20,
    ),
}


def _wait(values: list[Any]) -> Any:
    """Timings: NEVER beats any number; otherwise the longest wait."""
    vs = [v for v in values if v is not INHERIT]
    if not vs:
        return NEVER  # e.g. Being heard alone: no hint offers
    return NEVER if any(v is NEVER for v in vs) else max(vs)


def _limit(values: list[Any]) -> Any:
    """Caps: the smallest cap wins; None = no cap."""
    vs = [v for v in values if v not in (INHERIT, None)]
    return min(vs) if vs else None


def merge(needs: frozenset[Need]) -> PauseConfig:
    """Merge the chosen needs into one :class:`PauseConfig`."""
    if not needs:
        needs = frozenset({Need.FINDING_WORDS})
    ps = [PROFILES[n] for n in needs]

    def get(key: str, default: Any = INHERIT) -> list[Any]:
        return [p.get(key, default) for p in ps]

    banned: set[str] = set().union(*get("banned_phrases", set()))
    allowed = set().union(*get("allowed_phrases", set())) - banned

    return PauseConfig(
        needs=needs,
        backchannel_s=_wait(get("backchannel_s")),
        offer_hint_s=_wait(get("offer_hint_s")),
        max_wait_s=_wait(get("max_wait_s")),
        needs_complete_text=any(get("needs_complete_text", False)),
        allowed_phrases=frozenset(allowed),
        banned_phrases=frozenset(banned),
        feedback=frozenset(set().union(*get("feedback", set()))),
        max_session_min=_limit(get("max_session_min")),
        max_turns=_limit(get("max_turns")),
        rest_every_turns=_limit(get("rest_every_turns")),
    )
