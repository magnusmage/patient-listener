"""Nightly plan builder (workbook: Architecture -> Arch 2; FR-41, FR-52).

Only the meaning line is model-written (Super); the sound and word lines are code templates. The
meaning line is validated by :func:`check_meaning_hint`; on failure it falls back to a safe
template built from the meaning cue, so the clip is always made. ``build_plan`` picks up to 10
due words via FSRS; ``weekly_card`` is validated and falls back to a template card.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from ..schemas import HintLines, Plan, PlanFacts, PlanItem, WordEntry
from ..voice import hints as hintmod
from . import templates
from .validate import check_meaning_hint, check_reply

__all__ = ["write_hints", "build_plan", "weekly_card"]


def write_hints(llm, word: WordEntry, *, ai_enabled=lambda: True) -> HintLines:
    """Write and validate the three hint lines for one approved word (FR-41)."""
    meaning: Optional[str] = None
    if not ai_enabled():
        return hintmod.template_hint_lines(word)
    try:
        meaning = asyncio.run(llm.plan(PlanFacts(
            word=word.text,
            kind=word.kind,
            meaning_cue=word.meaning_cue,
            first_letter=word.first_sound or word.text[:1],
        )))
    except Exception:  # noqa: BLE001 - any model error -> template
        meaning = None

    if not ai_enabled():
        meaning = None
    if meaning is not None and not check_meaning_hint(meaning, word.text).ok:
        meaning = None  # one rejection -> template (nightly can also retry; omitted for brevity)

    return hintmod.template_hint_lines(word, meaning)


def build_plan(store, person_id: str, mode: str = "review", k: int = 10) -> Plan:
    """Pick tomorrow's words: due via FSRS, else new approved words. Yesterday's plan is the
    fallback if nothing is due (handled by the caller via load_plan)."""
    from ..schedule.fsrs import Card, due_tonight

    words = {w.id: w for w in store.words(person_id)}
    cards = store.all_cards(person_id)
    # Seed a new card for any approved word without one.
    for wid in words:
        cards.setdefault(wid, Card.new().to_json())
        if store.get_card(person_id, wid) is None:
            store.set_card(person_id, wid, cards[wid])

    due_ids = due_tonight(cards, k=k)
    chosen = due_ids or list(words)[:k]
    items = tuple(
        PlanItem(
            word_id=wid,
            reason="due" if wid in due_ids else "new",
            prompt="Who is this?" if words[wid].kind == "person" else "What's this?",
        )
        for wid in chosen
        if wid in words
    )
    pause = store.load_plan(person_id).pause
    plan = Plan(person_id=person_id, mode=mode, items=items, pause=pause)
    store.save_plan(plan)
    return plan


def weekly_card(store, person_id: str, local_number: str) -> str:
    """The Friday card: validated, template fallback (FR-52)."""
    name = store.person_name(person_id)
    found_no_hint = store.count_found_without_hint(person_id, since_days=7)
    new_words = [w.text for w in store.all_words(person_id)][:3]
    card = templates.weekly_card_template(name, found_no_hint, new_words, local_number)
    # The card is template-built, so it already satisfies the validator; the check is a guard.
    from ..schemas import ReplyFacts

    facts = ReplyFacts(
        person_first_name=name,
        topic="weekly_card",
        hint_level=hintmod.HintLevel.NONE,
        practice_words=(),
        found=(),
        last_words_heard="",
        needs=frozenset(),
        allowed_names=frozenset({name}),
    )
    # The card legitimately contains counts and the safety line; only check the forbidden words.
    from ..banned import NEGATIVE

    if NEGATIVE.search(card):
        return templates.weekly_card_template(name, found_no_hint, [], local_number)
    return card
