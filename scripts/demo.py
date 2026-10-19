#!/usr/bin/env python3
"""Offline 'talk to it' demo. Plays a scripted session through the live patience controller and
prints a J1-style trace, the attempt log and the interruption count. No GPU, no network.

    PYTHONPATH=src python scripts/demo.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from patient_listener.llm.reply import TemplateLlm  # noqa: E402
from patient_listener.store.sqlite_store import SqliteStore  # noqa: E402
from patient_listener.tools.seed import seed_margaret  # noqa: E402
from patient_listener.voice.actions import (  # noqa: E402
    LogAttempt,
    Play,
    Praise,
    ShowHint,
    Speak,
)
from patient_listener.voice.merge import merge  # noqa: E402
from patient_listener.voice.session import SessionEngine  # noqa: E402


def describe(a) -> str:
    if isinstance(a, Play):
        return f"play clip: {a.key}"
    if isinstance(a, ShowHint):
        return f"show hint {int(a.level)}: {a.word.text}"
    if isinstance(a, Praise):
        return f"praise: Yes, {a.word.text}."
    if isinstance(a, LogAttempt):
        at = a.attempt
        return (
            f"LOG attempt: word={at.word_id} hint={int(at.hint_level)} "
            f"outcome={at.outcome.value} score={at.match_score:.2f}"
        )
    if isinstance(a, Speak):
        return f"speak: {a.text}"
    return type(a).__name__


def main() -> None:
    store = SqliteStore()
    pid = seed_margaret(store)
    words = store.words(pid)
    leo = next(w for w in words if w.text == "Leo")
    eng = SessionEngine(
        cfg=merge(store.person_needs(pid)),
        store=store,
        llm=TemplateLlm(),
        person_id=pid,
        session_id="demo",
        first_name="Margaret",
        words=words,
    )

    # Margaret is shown a photo of Leo, pauses, takes a hint, then finds the word.
    script = [
        ("prompt", leo, "photo: Leo at the beach", 0.0),
        ("speech", 0.0),
        ("heard", "my grandson is", 2.0),
        ("silence", 2.0), ("silence", 4.0), ("silence", 6.0),  # mm at 6 s (quiet 4)
        ("silence", 8.0), ("silence", 9.0),                    # offer at 9 s (quiet 7)
        ("yes", 9.5),                                          # "yes" -> meaning hint
        ("heard", "Leo", 11.0),                                # found
    ]

    print("=" * 66)
    print("Patient Listener — offline demo (Margaret, Finding words)")
    print("=" * 66)
    for ev in script:
        before = len(eng.log)
        acts = eng.feed(ev)
        tag = ev[0]
        detail = ""
        if tag in ("heard", "typed"):
            detail = f' "{ev[1]}"'
        elif tag in ("prompt",):
            detail = f' [{ev[2]}]'
        t = ev[-1] if isinstance(ev[-1], (int, float)) else 0.0
        print(f"\n[{t:5.1f}s] person: {tag}{detail}")
        for a in acts:
            print(f"          listener -> {describe(a)}")

    print("\n" + "-" * 66)
    print(f"interruptions (target 0): {eng.interruptions}")
    print("attempt log:")
    for row in store.attempts_for(pid):
        print(
            f"  word={row['word_id']} hint={row['hint_level']} "
            f"outcome={row['outcome']} score={row['match_score']:.2f}"
        )
    print("No audio or transcript was stored — only the attempt rows above.")


if __name__ == "__main__":
    main()
