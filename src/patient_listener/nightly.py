"""Nightly job entry point (Serverless Job; D-11).

For each person: pick tomorrow's due words via FSRS, write and validate the hint lines for every
approved word, build the plan, and on Fridays build the weekly card. Runs offline with the
template LLM; on the deploy box the ``Llm`` is :class:`TokenFactoryLlm` and the clips are
rendered by the voice endpoint's ``/internal/render``.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .llm import plan as planmod
from .llm.reply import TemplateLlm
from .ports import Llm
from .store.sqlite_store import SqliteStore
from .voice.safety import emergency_number


def run_for_person(
    store: SqliteStore,
    person_id: str,
    llm: Optional[Llm] = None,
    today: Optional[date] = None,
    region: str = "UK",
) -> dict:
    llm = llm or TemplateLlm()
    today = today or date.today()

    # 1. Validate + store hint lines for every approved word.
    hinted = 0
    for word in store.words(person_id):
        lines = planmod.write_hints(llm, word)
        store.set_word_hints(word.id, lines)
        hinted += 1

    # 2. Build tomorrow's plan (due words via FSRS).
    plan = planmod.build_plan(store, person_id)

    # 3. Friday: the weekly card.
    card = None
    if today.weekday() == 4:  # Monday=0 ... Friday=4
        card = planmod.weekly_card(store, person_id, emergency_number(region))

    return {
        "person_id": person_id,
        "hinted_words": hinted,
        "plan_items": len(plan.items),
        "weekly_card": card,
    }


def main(db: str = "pl.db") -> None:  # pragma: no cover - CLI
    store = SqliteStore(db)
    # In production, iterate over every active person at 02:00 local.
    print("nightly: run run_for_person(store, person_id) per person")


if __name__ == "__main__":  # pragma: no cover
    main()
