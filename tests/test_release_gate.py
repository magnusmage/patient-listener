"""The release gate (workbook: Evaluation -> Release gate). Mirrors ``tests/eval/gate.py``:
these seven conditions decide whether the build ships. Run over representative P/W/S/F/N cases.
"""

from __future__ import annotations

import asyncio
import unittest

from patient_listener.llm.reply import TemplateLlm, produce_reply
from patient_listener.llm.validate import check_reply
from patient_listener.ports import Llm
from patient_listener.schemas import ReplyFacts
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_margaret
from patient_listener.types import HintLevel, Need
from patient_listener.voice.actions import LogAttempt, Play, ShowHint, SafetyStop
from patient_listener.voice.matcher import best_match
from patient_listener.voice.merge import merge
from patient_listener.voice.safety import check as safety_check
from patient_listener.voice.session import SessionEngine


def _engine(needs, words, session_id="g"):
    store = SqliteStore()
    pid = "demo"
    store.add_person(pid, "Margaret", needs)
    for w in words:
        store.add_word_draft(w.id, pid, w.text, w.kind, w.meaning_cue, w.first_sound, "slt")
        store.approve_word(w.id, "slt")
    live = store.words(pid)
    eng = SessionEngine(cfg=merge(needs), store=store, llm=TemplateLlm(),
                        person_id=pid, session_id=session_id, first_name="Margaret", words=live)
    return eng, store, {w.text: w for w in live}


class RevealLlm(Llm):
    async def reply(self, facts, timeout_s): return "Is that Biscuit here?"
    async def plan(self, facts): return None
    async def is_complete(self, q, t, timeout_s): return True


# --- P: interruptions in pauses <= 15 s ---------------------------------------

def gate_p_interruptions() -> int:
    from support import word
    total = 0
    for pause in [2, 4, 6, 8, 10, 12, 15]:
        eng, store, w = _engine(frozenset({Need.FINDING_WORDS}), [word("w", "Leo")], f"p{pause}")
        eng.feed(("prompt", w["Leo"], "photo", 0.0))
        eng.feed(("speech", 0.0)); eng.feed(("heard", "my grandson is", 1.0))
        t = 1.0
        while t <= 1.0 + pause:
            eng.feed(("silence", round(t, 1))); t += 0.5
        eng.feed(("heard", "Leo", 1.0 + pause + 0.1))
        total += eng.interruptions
    # um-chain: fillers reset the clock, never an interruption.
    eng, store, w = _engine(frozenset({Need.FINDING_WORDS}), [word("w", "Leo")], "pum")
    eng.feed(("prompt", w["Leo"], "photo", 0.0))
    for i in range(10):
        eng.feed(("speech", float(i))); eng.feed(("silence", float(i) + 0.4))
    total += eng.interruptions
    return total


# --- W: found-word precision ---------------------------------------------------

def gate_w_precision() -> float:
    from support import word
    words = [word("w-leo", "Leo", first_sound="L"),
             word("w-kettle", "kettle", "object", "boil water", "K"),
             word("w-whitby", "Whitby", "place", "seaside", "W")]
    # (heard, true_target_or_None). Only >= 0.90 are auto-logged as found.
    cases = [
        (["Leo"], "w-leo"),
        (["kettle"], "w-kettle"),
        (["Whitby"], "w-whitby"),
        (["Leah"], None),      # 0.74 -> confirm, not auto-logged
        (["teapot"], None),    # 0.33 -> not a match
        (["my", "grandson", "is", "Leo"], "w-leo"),
    ]
    logged = 0
    correct = 0
    for tokens, truth in cases:
        m = best_match(tokens, words)
        if m is not None and m.is_found:  # auto-logged as found
            logged += 1
            if m.word.id == truth:
                correct += 1
    return correct / logged if logged else 1.0


# --- S: safety recall ----------------------------------------------------------

def gate_s_recall() -> float:
    cases = [
        "my arm feels funny and words are worse today",
        "my face feels droopy",
        "my arm is weak",
        "I can't speak like yesterday",
        "I'm useless",
        "what's the point",
        "no... point... me",
        "my voice has been hoarse for 3 weeks",
        "I keep choking on water",
        "I get breathless",
        "suddenly my hearing went",
        "I have a new stammer",
    ]
    caught = sum(1 for c in cases if safety_check(c) is not None)
    return caught / len(cases)


# --- reveal reaching the person ------------------------------------------------

def gate_reveal_reached_person() -> int:
    facts = ReplyFacts(
        person_first_name="Margaret", topic="photo", hint_level=HintLevel.NONE,
        practice_words=("Leo", "Biscuit", "kettle"), found=(), last_words_heard="",
        needs=frozenset({Need.FINDING_WORDS}),
        allowed_names=frozenset({"Margaret", "Leo", "Biscuit", "kettle"}),
    )
    reached = 0
    # Direct validator check on adversarial lines.
    for line in ["Is that Biscuit?", "Say kettle now.", "The puppy is Biscuit, isn't it?"]:
        if check_reply(line, facts).ok:
            reached += 1
    # Through the orchestration (reject -> retry -> template).
    r = asyncio.run(produce_reply(RevealLlm(), facts, timeout_s=0.1))
    if not r.used_template or "Biscuit" in r.text:
        reached += 1
    return reached


# --- N: Getting words out never speaks in a block ------------------------------

def gate_words_out_spoke_in_block() -> int:
    from support import word
    total = 0
    for block in [3, 5, 8, 12]:
        eng, store, w = _engine(frozenset({Need.WORDS_OUT}), [word("w", "Leo")], f"n{block}")
        eng.feed(("prompt", None, "phone call", 0.0))
        eng.feed(("speech", 0.0)); eng.feed(("heard", "I'd like to my my", 1.0))
        t = 1.0
        while t <= 1.0 + block:
            eng.feed(("silence", round(t, 1))); t += 0.5
        total += sum(1 for a in eng.log if isinstance(a, (Play, ShowHint)))
    return total


# --- N: Being clear never logs a find without the tap --------------------------

def gate_clear_unconfirmed_found() -> int:
    from support import word
    eng, store, w = _engine(frozenset({Need.BEING_CLEAR}), [word("w", "kettle", "object", "boil", "K")], "nc")
    eng.feed(("prompt", w["kettle"], "photo", 0.0))
    eng.feed(("heard", "kettle", 1.0))  # exact match but no tap
    return len([a for a in store.attempts_for("demo")])


# --- F: every fault yields a line ---------------------------------------------

def gate_fallback_coverage() -> float:
    facts = ReplyFacts(
        person_first_name="Margaret", topic="photo", hint_level=HintLevel.NONE,
        practice_words=("Leo",), found=(), last_words_heard="",
        needs=frozenset({Need.FINDING_WORDS}), allowed_names=frozenset({"Margaret", "Leo"}),
    )
    results = [
        asyncio.run(produce_reply(RevealLlm(), facts, timeout_s=0.05)),
        asyncio.run(produce_reply(TemplateLlm(), facts, timeout_s=0.05)),
        asyncio.run(produce_reply(TemplateLlm(), facts, timeout_s=0.05, ai_enabled=False)),
    ]
    produced = sum(1 for r in results if r.text and r.text.strip())
    return produced / len(results)


GATES = {
    "P.interruptions_le_15s": (lambda: gate_p_interruptions(), lambda v: v == 0),
    "W.precision": (lambda: gate_w_precision(), lambda v: v >= 0.95),
    "S.recall": (lambda: gate_s_recall(), lambda v: v == 1.0),
    "F.fallback_within_2s": (lambda: gate_fallback_coverage(), lambda v: v == 1.0),
    "reveal_reached_person": (lambda: gate_reveal_reached_person(), lambda v: v == 0),
    "N.words_out_spoke_in_block": (lambda: gate_words_out_spoke_in_block(), lambda v: v == 0),
    "N.clear_unconfirmed_found": (lambda: gate_clear_unconfirmed_found(), lambda v: v == 0),
}


class TestReleaseGate(unittest.TestCase):
    def test_all_gates_green(self):
        failures = []
        for name, (measure, passes) in GATES.items():
            value = measure()
            ok = passes(value)
            with self.subTest(gate=name):
                self.assertTrue(ok, f"{name} = {value}")
            if not ok:
                failures.append((name, value))
        self.assertEqual(failures, [], f"release gate failures: {failures}")


if __name__ == "__main__":
    unittest.main()
