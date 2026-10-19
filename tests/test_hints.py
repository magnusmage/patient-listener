"""Hint ladder (FR-20, FR-21, FR-41)."""

from __future__ import annotations

import unittest

from patient_listener.schemas import HintLines
from patient_listener.types import HintLevel
from patient_listener.voice.hints import (
    next_level,
    render,
    sound_line,
    template_hint_lines,
    word_line,
)

from support import word


class TestHints(unittest.TestCase):
    def test_templates(self):
        self.assertEqual(sound_line("k"), "It starts with K.")
        self.assertEqual(word_line("kettle"), "It's kettle. Say it with me: kettle.")

    def test_next_level_default_order(self):
        order = (HintLevel.MEANING, HintLevel.SOUND, HintLevel.WORD)
        self.assertEqual(next_level(HintLevel.NONE, order), HintLevel.MEANING)
        self.assertEqual(next_level(HintLevel.MEANING, order), HintLevel.SOUND)
        self.assertEqual(next_level(HintLevel.SOUND, order), HintLevel.WORD)
        self.assertEqual(next_level(HintLevel.WORD, order), HintLevel.WORD)  # never past last

    def test_template_meaning_never_contains_word(self):
        lines = template_hint_lines(word("w", "kettle", first_sound="K"), meaning="A kettle thing")
        self.assertNotIn("kettle", lines.meaning.lower())

    def test_render_uses_pretten_hints(self):
        hints = HintLines(meaning="You boil water in it.", sound="It starts with K.",
                          word="It's kettle. Say it with me: kettle.")
        w = word("w", "kettle", first_sound="K", hints=hints)
        step = render(w, HintLevel.MEANING)
        self.assertEqual(step.text, "You boil water in it.")
        self.assertEqual(step.clip_key, "hint:w:1")

    def test_render_falls_back_to_template(self):
        w = word("w", "kettle", meaning_cue="you boil water in it", first_sound="K", hints=None)
        step = render(w, HintLevel.SOUND)
        self.assertEqual(step.text, "It starts with K.")


if __name__ == "__main__":
    unittest.main()
