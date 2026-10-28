"""Word visual selection and compatibility with the existing prompt event."""
import unittest

from patient_listener.app.word_emoji import word_emoji
from patient_listener.app.presenter import prompt_payload
from patient_listener.schemas import WordEntry
from patient_listener.types import Feedback


class WordEmojiTests(unittest.TestCase):
    def test_library_matches_new_words_without_a_curated_entry(self):
        self.assertEqual(word_emoji("banana", "food"), "🍌")
        self.assertEqual(word_emoji("bicycle", "object"), "🚲")

    def test_common_synonyms_and_approximate_visuals(self):
        self.assertEqual(word_emoji("BISCUIT!", "food"), "🍪")
        self.assertEqual(word_emoji("kettle", "object"), "🫖")

    def test_phrase_and_plural(self):
        self.assertEqual(word_emoji("a cup of tea", "phrase"), "☕")
        self.assertEqual(word_emoji("bananas", "food"), "🍌")

    def test_unknowns_and_names_use_fallback_without_fuzzy_guesses(self):
        self.assertEqual(word_emoji("quuxapplequux", "object"), "🧺")
        self.assertEqual(word_emoji("Leo", "person"), "👤")
        self.assertEqual(word_emoji("Whitby", "place"), "📍")

    def test_live_prompt_keeps_contract_without_target_label(self):
        word = WordEntry(id="w-new", person_id="p", text="banana", kind="food")
        payload = prompt_payload(word, frozenset({Feedback.WORD_FOUND}), "finding_words")
        self.assertEqual(payload["photo"], "🍌")
        self.assertNotIn("banana", payload["topic"])
        self.assertEqual(set(payload), {"topic", "photo", "text", "profile", "feedback"})

    def test_open_conversation_is_unchanged(self):
        self.assertEqual(prompt_payload(None, frozenset(), "words_out")["photo"], "🗓️")
