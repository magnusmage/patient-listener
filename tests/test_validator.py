"""The validator (FR-21, FR-24, DS-C03/04/05, W-11). No line that fails reaches the person."""

from __future__ import annotations

import unittest

from patient_listener.schemas import ReplyFacts
from patient_listener.types import HintLevel, Need
from patient_listener.llm.validate import check_meaning_hint, check_reply


def facts(**kw) -> ReplyFacts:
    base = dict(
        person_first_name="Margaret",
        topic="photo",
        hint_level=HintLevel.NONE,
        practice_words=("Leo", "Biscuit", "kettle", "Whitby"),
        found=(),
        last_words_heard="",
        needs=frozenset({Need.FINDING_WORDS}),
        allowed_names=frozenset({"Margaret", "Leo", "Biscuit", "kettle", "Whitby"}),
        names_heard_this_turn=frozenset(),
        pending_confirm=False,
        banned_phrases=frozenset(),
    )
    base.update(kw)
    return ReplyFacts(**base)


class TestValidator(unittest.TestCase):
    def test_reveal_rejected(self):
        # W-11: the model reveals a not-yet-found word at hint level 0.
        v = check_reply("Is that Biscuit the puppy?", facts(hint_level=HintLevel.NONE))
        self.assertFalse(v.ok)
        self.assertEqual(v.reason, "reveals_word")

    def test_found_word_allowed(self):
        v = check_reply("What's Leo doing in the photo?", facts(found=("Leo",)))
        self.assertTrue(v.ok, v.reason)

    def test_reveal_allowed_at_level_3(self):
        v = check_reply("It's Biscuit. Say it with me.", facts(hint_level=HintLevel.WORD))
        self.assertTrue(v.ok, v.reason)

    def test_too_long(self):
        long = " ".join(["word"] * 16)
        self.assertEqual(check_reply(long, facts()).reason, "too_long")

    def test_unknown_name(self):
        self.assertEqual(check_reply("Tell me about Gandalf.", facts()).reason, "unknown_name")

    def test_heard_name_allowed(self):
        v = check_reply("Tell me about Liam.", facts(names_heard_this_turn=frozenset({"Liam"})))
        self.assertTrue(v.ok, v.reason)

    def test_profile_ban_getting_words_out(self):
        # DS-C05: never 'slow down', 'relax', 'take your time' for a stammer.
        f = facts(needs=frozenset({Need.WORDS_OUT}), banned_phrases=frozenset(
            {"slow", "relax", "breathe", "calm", "take_your_time", "no_rush"}
        ), practice_words=(), allowed_names=frozenset({"Margaret"}))
        self.assertEqual(check_reply("Just relax and take your time.", f).reason, "profile_ban")

    def test_medical_rejected(self):
        self.assertEqual(check_reply("Change your medication dose.", facts()).reason, "medical")

    def test_negative_rejected(self):
        self.assertEqual(check_reply("No, that's wrong.", facts()).reason, "negative_feedback")

    def test_exclamation_rejected(self):
        self.assertEqual(check_reply("Well done!!", facts()).reason, "negative_feedback")

    def test_unconfirmed_understood_rejected_being_clear(self):
        f = facts(needs=frozenset({Need.BEING_CLEAR}), pending_confirm=True)
        self.assertEqual(check_reply("I understood you perfectly.", f).reason, "unconfirmed")

    def test_clean_line_ok(self):
        self.assertTrue(check_reply("Take your time. What else can you see?",
                                    facts(needs=frozenset({Need.FINDING_WORDS}))).ok)


    def test_reported_appearance_comparison_is_rejected(self):
        f = facts(last_words_heard="Is this a biscuit?", found=("Biscuit",))
        for line in ("You look like a fox.", "You seem like a fox.",
                     "I can see a fox.", "Your face looks like a fox."):
            with self.subTest(line=line):
                self.assertEqual(check_reply(line, f).reason, "unsupported_claim")

    def test_unrelated_lowercase_content_is_rejected(self):
        f = facts(last_words_heard="Is this a biscuit?", found=("Biscuit",))
        for line in ("Tell me about the fox.", "The spaceship is lovely.", ""):
            self.assertEqual(check_reply(line, f).reason, "ungrounded_content")

    def test_question_can_use_the_persons_own_content(self):
        f = facts(last_words_heard="I saw a fox near the garden.")
        self.assertTrue(check_reply("Tell me more about the fox.", f).ok)
        # Heard content does not license the AI to claim visual access.
        self.assertEqual(check_reply("I can see the fox.", f).reason, "unsupported_claim")

    def test_neutral_followup_does_not_need_new_content(self):
        f = facts(last_words_heard="Is this a biscuit?", found=("Biscuit",))
        self.assertTrue(check_reply("Thanks. What else would you like to say?", f).ok)


class TestMeaningHint(unittest.TestCase):
    def test_meaning_must_not_contain_word(self):
        self.assertFalse(check_meaning_hint("A kettle boils water.", "kettle").ok)

    def test_meaning_must_not_start_with_first_two_letters(self):
        self.assertFalse(check_meaning_hint("Something ketchup-coloured.", "kettle").ok)

    def test_good_meaning_ok(self):
        self.assertTrue(check_meaning_hint("You boil water in it.", "kettle").ok)

    def test_meaning_too_long(self):
        self.assertFalse(check_meaning_hint(" ".join(["x"] * 13), "kettle").ok)


if __name__ == "__main__":
    unittest.main()
