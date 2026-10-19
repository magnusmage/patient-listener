"""End-to-end dry-run scenarios through the session engine (workbook: Dry runs).
No audio, no GPU, no network: the logic-level voice loop."""

from __future__ import annotations

import unittest

from patient_listener.llm.reply import TemplateLlm
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all, seed_margaret
from patient_listener.types import HintLevel, Need, State
from patient_listener.voice.actions import (
    Confirm,
    EndTurn,
    LogAttempt,
    Play,
    SafetyStop,
    ShowHint,
)
from patient_listener.voice.merge import merge
from patient_listener.voice.session import SessionEngine


def _margaret_engine(session_id="s", needs=None):
    store = SqliteStore()
    pid = seed_margaret(store)
    needs = needs or store.person_needs(pid)
    words = store.words(pid)
    eng = SessionEngine(
        cfg=merge(needs), store=store, llm=TemplateLlm(),
        person_id=pid, session_id=session_id, first_name="Margaret", words=words,
    )
    return eng, store, {w.text: w for w in words}


class TestScenarios(unittest.TestCase):
    def test_scenario1_found_after_meaning_hint(self):
        eng, store, w = _margaret_engine("s1")
        eng.feed(("prompt", w["Leo"], "photo: Leo at the beach", 0.0))
        eng.feed(("speech", 0.0)); eng.feed(("heard", "my grandson is", 2.0))
        for t in [2.0, 4.0, 6.0, 8.0, 9.0]:
            eng.feed(("silence", t))  # mm@6, offer@9
        eng.feed(("yes", 9.5)); eng.feed(("heard", "Leo", 11.0))
        a = store.attempts_for(eng.person_id)[-1]
        self.assertTrue(any(isinstance(x, ShowHint) and x.level == HintLevel.MEANING for x in eng.log))
        self.assertEqual((a["hint_level"], a["outcome"]), (1, "found"))
        self.assertEqual(eng.interruptions, 0)

    def test_scenario2_sound_hint_needed(self):
        eng, store, w = _margaret_engine("s2")
        eng.feed(("prompt", w["kettle"], "photo: kitchen", 0.0))
        eng.feed(("help", 3.0))  # Help -> hint 1 (meaning)
        eng.feed(("help", 13.0))  # Help again -> hint 2 (sound)
        eng.feed(("heard", "kettle", 14.0))
        a = store.attempts_for(eng.person_id)[-1]
        self.assertEqual((a["hint_level"], a["outcome"]), (2, "found"))

    def test_scenario3_long_pause_no_help(self):
        eng, store, w = _margaret_engine("s3")
        eng.feed(("prompt", w["Whitby"], "holiday", 0.0))
        eng.feed(("speech", 0.0)); eng.feed(("heard", "where did we go", 2.0))
        for t in [2.0, 4.0, 6.0, 8.0, 9.0]:
            eng.feed(("silence", t))  # mm@6, offer@9
        eng.feed(("no", 9.5))  # "no, no..." -> back to listening, clock restarts
        for t in [10.0, 12.0, 14.0]:
            eng.feed(("silence", t))  # mm@14 = backchannel 2 of 2
        eng.feed(("heard", "Whitby", 15.0))  # found with no hint
        mm = [x for x in eng.log if isinstance(x, Play) and x.key == "mm"]
        a = store.attempts_for(eng.person_id)[-1]
        self.assertEqual(len(mm), 2)  # at most 2 per turn
        self.assertEqual((a["hint_level"], a["outcome"]), (0, "found"))  # best outcome
        self.assertEqual(eng.interruptions, 0)

    def test_scenario4_different_word(self):
        eng, store, w = _margaret_engine("s4")
        eng.feed(("prompt", w["kettle"], "photo: kettle", 0.0))
        eng.feed(("heard", "teapot", 2.0))  # 0.33 -> not a match; nothing logged
        self.assertEqual(store.attempts_for(eng.person_id), [])
        eng.feed(("help", 3.0))  # hint 1
        eng.feed(("heard", "kettle", 5.0))
        a = store.attempts_for(eng.person_id)[-1]
        self.assertEqual((a["hint_level"], a["outcome"]), (1, "found"))

    def test_scenario5_asr_unsure_confirm_no(self):
        eng, store, w = _margaret_engine("s5")
        eng.feed(("prompt", w["Leo"], "photo", 0.0))
        acts = eng.feed(("heard", "Leah", 2.0))  # 0.74 -> confirm
        self.assertTrue(any(isinstance(x, Confirm) for x in acts))
        self.assertEqual(eng.controller.state, State.CONFIRMING)
        eng.feed(("no", 3.0))  # "no... Liam" -> not this word
        self.assertEqual(store.attempts_for(eng.person_id), [])  # nothing logged
        self.assertEqual(eng.controller.state, State.LISTENING)

    def test_scenario7_stroke_safety_stop(self):
        eng, store, w = _margaret_engine("s7")
        eng.feed(("prompt", w["Leo"], "photo", 0.0))
        acts = eng.feed(("heard", "my arm feels funny and words are worse today", 2.0))
        self.assertTrue(any(isinstance(x, SafetyStop) for x in acts))
        self.assertEqual(eng.safety_card, "stroke_signs")
        self.assertTrue(eng.carer_alerted)
        self.assertEqual(eng.controller.state, State.SAFETY_STOP)

    def test_scenario8_carer_draft_needs_person_approval(self):
        # Agent drafts; it has no approve path (FR-40, S-09). A person approves in the console.
        # Fresh person (no pre-seeded words) so the draft is genuinely the first of its kind.
        store = SqliteStore()
        pid = "p-carer"
        store.add_person(pid, "Margaret", frozenset({Need.FINDING_WORDS}))
        store.add_word_draft("w-rex", pid, "Rex", "person", "Leo's new puppy", added_by="carer")
        self.assertNotIn("Rex", [x.text for x in store.words(pid)])  # draft, not live
        store.approve_word("w-rex", by="carer")  # carer approves (no SLT linked)
        self.assertIn("Rex", [x.text for x in store.words(pid)])
        # Nightly builds and validates its hints (meaning never contains the word).
        from patient_listener.nightly import run_for_person
        run_for_person(store, pid)
        rex = next(x for x in store.words(pid) if x.text == "Rex")
        self.assertIsNotNone(rex.hints)
        self.assertNotIn("rex", rex.hints.meaning.lower())
        self.assertEqual(rex.hints.sound, "It starts with R.")

    def test_scenario9_stammer_complete_check(self):
        store = SqliteStore()
        eng = SessionEngine(
            cfg=merge(frozenset({Need.WORDS_OUT})), store=store, llm=TemplateLlm(),
            person_id="demo-daniyal", session_id="s9", first_name="Daniyal", words=[],
        )
        store.add_person("demo-daniyal", "Daniyal", frozenset({Need.WORDS_OUT}))
        eng.feed(("prompt", None, "phone call to the bank", 0.0))
        eng.feed(("speech", 1.2)); eng.feed(("heard", "I'd like to check my my my", 2.9))
        for t in [3.0, 5.0, 8.0, 11.0]:
            eng.feed(("silence", t))  # @11 quiet=8 -> CheckComplete -> incomplete
        sounds = [x for x in eng.log if isinstance(x, (Play, ShowHint))]
        self.assertEqual(sounds, [])  # no mm, no hint ever (FR-12, N-01..08)
        eng.feed(("speech", 12.0)); eng.feed(("heard", "account balance", 12.1))
        for t in [13.0, 16.0, 21.0]:
            eng.feed(("silence", t))  # @21 quiet=8 -> complete -> EndTurn + reply
        self.assertTrue(any(isinstance(x, EndTurn) for x in eng.log))
        self.assertEqual(eng.interruptions, 0)

    def test_scenario11_being_clear_no_find_without_tap(self):
        eng, store, w = _margaret_engine("s11", needs=frozenset({Need.BEING_CLEAR}))
        eng.feed(("prompt", w["kettle"], "photo", 0.0))
        acts = eng.feed(("heard", "kettle", 2.0))  # exact match, but must NOT auto-log
        self.assertTrue(any(isinstance(x, Confirm) for x in acts))
        self.assertEqual(store.attempts_for(eng.person_id), [])  # nothing found yet (FR-14)
        eng.feed(("confirm_tap", True, 3.0))  # the person taps the check
        a = store.attempts_for(eng.person_id)[-1]
        self.assertEqual(a["outcome"], "found")

    def test_being_clear_fix_does_not_log(self):
        eng, store, w = _margaret_engine("s11b", needs=frozenset({Need.BEING_CLEAR}))
        eng.feed(("prompt", w["kettle"], "photo", 0.0))
        eng.feed(("heard", "kettle", 2.0))
        eng.feed(("confirm_tap", False, 3.0))  # the person edits/rejects
        self.assertEqual(store.attempts_for(eng.person_id), [])


class TestJudgeMode(unittest.TestCase):
    def test_seed_three_profiles(self):
        store = SqliteStore()
        people = seed_all(store)
        self.assertEqual(set(people), {"margaret", "daniyal", "joseph"})
        self.assertEqual(len(store.words("demo-margaret")), 4)


if __name__ == "__main__":
    unittest.main()
