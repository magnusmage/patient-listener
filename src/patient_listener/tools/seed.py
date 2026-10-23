"""Seed a demo person (a persona, not a patient) for judge mode and dry runs.

Workbook scenario data: Margaret with Leo (grandson), Biscuit (Leo's puppy), kettle, Whitby.
Also seeds Daniyal (Getting words out) and Joseph (Being heard) for the three judge profiles.
"""

from __future__ import annotations

from ..store.sqlite_store import SqliteStore
from ..types import Need


def seed_margaret(store: SqliteStore) -> str:
    pid = "demo-margaret"
    if store.person_deleted(pid):
        return pid
    store.add_person(pid, "Margaret", frozenset({Need.FINDING_WORDS}))
    words = [
        ("w-leo", "Leo", "person", "Leo's your grandson, he's six", "L"),
        ("w-biscuit", "Biscuit", "person", "Leo's new puppy", "B"),
        ("w-kettle", "kettle", "object", "you boil water in it", "K"),
        ("w-whitby", "Whitby", "place", "the seaside town you visited", "W"),
    ]
    existing = {w.id for w in store.all_words(pid)}
    for wid, text, kind, cue, fs in words:
        if wid in existing:
            continue
        store.add_word_draft(wid, pid, text, kind, meaning_cue=cue, first_sound=fs, added_by="slt")
        store.approve_word(wid, by="slt")
    return pid


def seed_daniyal(store: SqliteStore) -> str:
    pid = "demo-daniyal"
    if store.person_deleted(pid):
        return pid
    store.add_person(pid, "Daniyal", frozenset({Need.WORDS_OUT}))
    return pid


def seed_joseph(store: SqliteStore) -> str:
    pid = "demo-joseph"
    if store.person_deleted(pid):
        return pid
    store.add_person(pid, "Joseph", frozenset({Need.BEING_HEARD}))
    return pid


def seed_all(store: SqliteStore) -> dict[str, str]:
    people = {
        "margaret": seed_margaret(store),
        "daniyal": seed_daniyal(store),
        "joseph": seed_joseph(store),
    }
    return {name: pid for name, pid in people.items() if store.person_exists(pid)}


if __name__ == "__main__":  # pragma: no cover
    s = SqliteStore("pl.db")
    print(seed_all(s))
