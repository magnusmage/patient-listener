"""Patience controller (DR-3, P-set, N-set). Pure code with a fake clock."""

from __future__ import annotations

import unittest

from patient_listener.schemas import PauseConfig
from patient_listener.types import HintLevel, Need, State
from patient_listener.voice.actions import (
    CheckComplete,
    MoveOn,
    OfferRest,
    Play,
    ShowHint,
    Stop,
)
from patient_listener.voice.controller import PatienceController

from support import cfg_for, run_silence, word


class TestTiming(unittest.TestCase):
    def test_never_speaks_before_4s(self):
        c = PatienceController(PauseConfig(), target=word())
        self.assertEqual(run_silence(c, 0.0, 3.9), [])

    def test_mm_at_4_then_offer_at_7(self):
        c = PatienceController(PauseConfig(), target=word())
        acts = run_silence(c, 0.0, 7.2)
        keys = [(t, a.key) for t, a in acts if isinstance(a, Play)]
        self.assertEqual([k for _, k in keys], ["mm", "offer_hint"])
        self.assertTrue(4.0 <= keys[0][0] < 4.2)
        self.assertTrue(7.0 <= keys[1][0] < 7.2)

    def test_speech_resets_clock(self):
        c = PatienceController(PauseConfig(), target=word())
        run_silence(c, 0.0, 3.5)
        c.on_speech(3.6)  # "um" counts as speech
        acts = run_silence(c, 3.7, 7.8)
        plays = [(t, a.key) for t, a in acts if isinstance(a, Play)]
        self.assertEqual(plays[0][1], "mm")
        self.assertTrue(7.6 <= plays[0][0] < 7.8)

    def test_move_on_at_20s(self):
        c = PatienceController(PauseConfig(), target=word())
        acts = run_silence(c, 0.0, 20.1)
        self.assertTrue(any(isinstance(a, MoveOn) for _, a in acts))

    def test_slt_can_lengthen_wait(self):
        c = PatienceController(PauseConfig(backchannel_s=6, offer_hint_s=12), target=word())
        acts = run_silence(c, 0.0, 11.9)
        keys = [a.key for _, a in acts if isinstance(a, Play)]
        self.assertEqual(keys, ["mm"])  # mm at 6; offer not yet (12)

    def test_person_can_switch_off_wait(self):
        # max_wait_s None: only Done ends the turn (WCAG 2.2.1); no move-on ever.
        c = PatienceController(PauseConfig(max_wait_s=None), target=word())
        acts = run_silence(c, 0.0, 60.0)
        self.assertFalse(any(isinstance(a, MoveOn) for _, a in acts))


class TestInvariants(unittest.TestCase):
    def test_never_speaks_during_speech(self):
        # FR-02 property: on_speech returns nothing for any state.
        for st in State:
            c = PatienceController(PauseConfig(), target=word(), state=st)
            self.assertEqual(c.on_speech(1.0), [])

    def test_at_most_two_mm_per_turn(self):
        # FR-03 / NFR-03: a second mm only after speech resets; never a third.
        c = PatienceController(PauseConfig(), target=word())
        mm = 0
        for _ in range(3):  # three silence bursts separated by speech
            for _, a in run_silence(c, 0.0, 5.0):
                if isinstance(a, Play) and a.key == "mm":
                    mm += 1
            c.on_speech(0.0)
        self.assertLessEqual(mm, 2)

    def test_hint_order_respected(self):
        c = PatienceController(PauseConfig(), target=word())
        levels = []
        for _ in range(4):
            acts = c.on_help()
            levels += [a.level for a in acts if isinstance(a, ShowHint)]
        self.assertEqual(levels, [HintLevel.MEANING, HintLevel.SOUND, HintLevel.WORD, HintLevel.WORD])

    def test_hint_order_can_be_swapped(self):
        order = (HintLevel.SOUND, HintLevel.MEANING, HintLevel.WORD)
        c = PatienceController(PauseConfig(hint_order=order), target=word())
        first = [a.level for a in c.on_help() if isinstance(a, ShowHint)][0]
        self.assertEqual(first, HintLevel.SOUND)


class TestGettingWordsOut(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg_for(Need.WORDS_OUT)

    def test_no_backchannel_no_hint_ever(self):
        # FR-12 / N-01..08: no mm, no hint, no Help effect during a block.
        c = PatienceController(self.cfg, target=word(), words=[word()])
        acts = run_silence(c, 0.0, 7.5)  # 4 s and 7 s pass
        self.assertEqual([a for _, a in acts if isinstance(a, (Play, ShowHint))], [])
        self.assertEqual(c.on_help(), [])  # Help does nothing in this profile

    def test_turn_ends_only_on_complete_text(self):
        c = PatienceController(self.cfg, target=word())
        acts = run_silence(c, 0.0, 8.1)  # max_wait 8 -> CheckComplete, not move-on
        self.assertTrue(any(isinstance(a, CheckComplete) for _, a in acts))
        self.assertFalse(any(isinstance(a, MoveOn) for _, a in acts))
        # Not complete -> keep waiting; Done ends it.
        self.assertEqual(c.on_complete(False, 8.2), [])
        self.assertTrue(any(isinstance(a, object) for a in c.on_done(9.0)))


class TestSavingEnergy(unittest.TestCase):
    def test_rest_every_5_and_cap_15(self):
        cfg = cfg_for(Need.SAVING_ENERGY)
        c = PatienceController(cfg, target=word())
        rests = 0
        for _ in range(16):
            acts = c.on_prompt(word(), now=0.0)
            if any(isinstance(a, OfferRest) for a in acts):
                rests += 1
            if any(isinstance(a, Stop) for a in acts):
                break
        self.assertGreaterEqual(rests, 2)  # rest offered at turns 6 and 11
        self.assertEqual(c.state, State.ENDED)  # session ended at the 16th prompt (cap 15)


if __name__ == "__main__":
    unittest.main()
