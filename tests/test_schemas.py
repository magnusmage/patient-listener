"""Schema validation and privacy invariants (FR-10, FR-23, NFR-06)."""

from __future__ import annotations

import dataclasses
import unittest

from patient_listener.schemas import (
    Attempt,
    PauseConfig,
    Plan,
    PlanItem,
    ValidationError,
    WordEntry,
)
from patient_listener.types import HintLevel, Need, Outcome, WordStatus


class TestSchemas(unittest.TestCase):
    def test_word_text_limit(self):
        with self.assertRaises(ValidationError):
            WordEntry(id="x", person_id="p", text="a" * 61, kind="object")

    def test_phrase_kind_and_limit(self):
        w = WordEntry(id="x", person_id="p", text="Can you open the window?", kind="phrase")
        self.assertTrue(w.is_phrase)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValidationError):
            WordEntry(id="x", person_id="p", text="Leo", kind="nickname")

    def test_no_diagnosis_field(self):
        # FR-10 / A-03: the schema has needs, never a diagnosis.
        fields = {f.name for f in dataclasses.fields(PauseConfig)}
        self.assertIn("needs", fields)
        self.assertNotIn("diagnosis", fields)
        self.assertNotIn("condition", fields)

    def test_attempt_has_no_text_or_audio(self):
        # FR-23 / NFR-06: an attempt stores only ids, numbers, a timestamp.
        fields = {f.name for f in dataclasses.fields(Attempt)}
        for forbidden in ("text", "audio", "transcript", "words", "diagnosis"):
            self.assertNotIn(forbidden, fields)

    def test_pause_ranges(self):
        with self.assertRaises(ValidationError):
            PauseConfig(offer_hint_s=3)  # below the 4 s floor
        with self.assertRaises(ValidationError):
            PauseConfig(max_wait_s=200)  # above the 120 s ceiling
        self.assertIsNone(PauseConfig(backchannel_s=None).backchannel_s)  # NEVER is valid

    def test_plan_max_items(self):
        items = tuple(PlanItem(word_id=f"w{i}", reason="due", prompt="?") for i in range(11))
        with self.assertRaises(ValidationError):
            Plan(person_id="p", mode="review", items=items, pause=PauseConfig())

    def test_attempt_score_range(self):
        with self.assertRaises(ValidationError):
            Attempt(
                session_id="s",
                word_id="w",
                hint_level=HintLevel.NONE,
                outcome=Outcome.FOUND,
                seconds_to_find=1.0,
                match_score=1.5,
                confirmed=True,
            )


if __name__ == "__main__":
    unittest.main()
