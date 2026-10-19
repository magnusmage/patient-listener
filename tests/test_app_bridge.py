"""Unit tests for the pure app-layer mapping: tokens, presenter, bridge.

No server, no socket - every function under test is a pure mapping or a stateless signer.
"""

from __future__ import annotations

import time
import unittest

from patient_listener.app import bridge, presenter
from patient_listener.app.tokens import TokenSigner
from patient_listener.schemas import Attempt, WordEntry
from patient_listener.types import Feedback, HintLevel, Outcome
from patient_listener.voice.actions import (
    Confirm,
    EndTurn,
    LogAttempt,
    MoveOn,
    OfferRest,
    Play,
    Praise,
    SafetyStop,
    ShowHint,
    Speak,
    Stop,
)
from patient_listener.voice.matcher import CONFIRM_THRESHOLD, FOUND_THRESHOLD, score


def _word(text="kettle", kind="object", first="K", cue="you boil water in it"):
    return WordEntry(id="w-x", person_id="p", text=text, kind=kind, meaning_cue=cue, first_sound=first)


class TokenTests(unittest.TestCase):
    def test_roundtrip(self):
        s = TokenSigner(secret="unit-secret")
        tok = s.issue("demo-margaret")
        claims = s.verify(tok)
        self.assertEqual(claims.person_id, "demo-margaret")

    def test_rejects_tampered(self):
        s = TokenSigner(secret="unit-secret")
        tok = s.issue("demo-margaret")
        with self.assertRaises(ValueError):
            s.verify(tok + "x")

    def test_rejects_wrong_secret(self):
        tok = TokenSigner(secret="a").issue("p")
        with self.assertRaises(ValueError):
            TokenSigner(secret="b").verify(tok)

    def test_rejects_expired(self):
        s = TokenSigner(secret="a", ttl_s=1)
        tok = s.issue("p", now=1000.0)
        with self.assertRaises(ValueError):
            s.verify(tok, now=1002.0)


class PresenterTests(unittest.TestCase):
    def test_feedback_key_picks_specific_over_default(self):
        fb = frozenset({Feedback.WORD_FOUND, Feedback.LOUDNESS})
        self.assertEqual(presenter.feedback_key(fb), "loudness")

    def test_prompt_payload_has_required_keys(self):
        p = presenter.prompt_payload(_word(), frozenset({Feedback.WORD_FOUND}), "finding_words")
        self.assertEqual(set(p), {"topic", "photo", "text", "profile", "feedback"})
        self.assertEqual(p["feedback"], "word_found")

    def test_prompt_payload_open_when_no_word(self):
        p = presenter.prompt_payload(None, frozenset({Feedback.WORD_FOUND}), "words_out")
        self.assertIn("ready", p["text"].lower())

    def test_safety_card_stroke_has_emergency_number(self):
        card = presenter.safety_card("stroke_signs", region="UK")
        self.assertEqual(card["number"], "999")
        self.assertIn("999", card["title"])

    def test_close_variant_lands_in_confirm_band(self):
        for target in ("Leo", "Biscuit", "kettle", "Whitby"):
            near = presenter.close_variant(target)
            s = score(near, target)
            self.assertTrue(
                CONFIRM_THRESHOLD <= s < FOUND_THRESHOLD,
                f"{target!r}->{near!r} scored {s:.3f}, expected confirm band",
            )


class BridgeActionTests(unittest.TestCase):
    def setUp(self):
        self.ctx = bridge.EmitContext(feedback="word_found")

    def test_play_mm(self):
        ev = bridge.action_to_events(Play("mm"), self.ctx)
        self.assertEqual(ev, [{"type": "backchannel", "key": "mm", "caption": "mm"}])

    def test_play_offer_hint(self):
        self.assertEqual(bridge.action_to_events(Play("offer_hint"), self.ctx), [{"type": "offerHint"}])

    def test_play_hint_clip_is_silent_in_text_mode(self):
        self.assertEqual(bridge.action_to_events(Play("hint:w-x:1"), self.ctx), [])

    def test_show_hint(self):
        ev = bridge.action_to_events(ShowHint(_word(), HintLevel.SOUND), self.ctx)[0]
        self.assertEqual(ev["type"], "hint")
        self.assertEqual(ev["level"], 2)
        self.assertEqual(ev["letter"], "K")
        self.assertEqual(ev["word"], "kettle")

    def test_confirm_word_found_mode(self):
        ev = bridge.action_to_events(Confirm(_word()), self.ctx)
        self.assertEqual(ev, [{"type": "confirm", "word": "kettle"}])

    def test_confirm_what_i_heard_mode(self):
        ctx = bridge.EmitContext(feedback="what_i_heard", last_heard="the garden")
        ev = bridge.action_to_events(Confirm(_word("the garden")), ctx)
        self.assertEqual(ev, [{"type": "whatIHeard", "text": "the garden"}])

    def test_praise_uses_ctx_hint_level(self):
        ctx = bridge.EmitContext(hint_level=1)
        ev = bridge.action_to_events(Praise(_word()), ctx)
        self.assertEqual(ev, [{"type": "found", "word": "kettle", "hintLevel": 1}])

    def test_log_attempt(self):
        a = Attempt(
            session_id="s", word_id="w-x", hint_level=HintLevel.NONE, outcome=Outcome.FOUND,
            seconds_to_find=2.0, match_score=0.97, confirmed=True,
        )
        ev = bridge.action_to_events(LogAttempt(a), self.ctx)[0]
        self.assertEqual(ev["type"], "attempt")
        self.assertEqual(ev["word_id"], "w-x")
        self.assertEqual(ev["outcome"], "found")

    def test_moveon_speak_offerrest(self):
        self.assertEqual(bridge.action_to_events(MoveOn(), self.ctx), [{"type": "moveOn"}])
        self.assertEqual(bridge.action_to_events(Speak("hello"), self.ctx), [{"type": "reply", "text": "hello"}])
        self.assertEqual(bridge.action_to_events(OfferRest(), self.ctx), [{"type": "restOffer"}])

    def test_safety_stop(self):
        ev = bridge.action_to_events(SafetyStop("stroke_signs"), self.ctx)[0]
        self.assertEqual(ev["type"], "safety")
        self.assertEqual(ev["card"], "stroke_signs")

    def test_stop_carries_found(self):
        ctx = bridge.EmitContext(found=["Leo", "kettle"])
        ev = bridge.action_to_events(Stop(), ctx)[0]
        self.assertEqual(ev["type"], "ended")
        self.assertEqual(ev["found"], ["Leo", "kettle"])

    def test_end_turn_is_silent(self):
        self.assertEqual(bridge.action_to_events(EndTurn(), self.ctx), [])


class BridgeMessageTests(unittest.TestCase):
    def test_direct_messages(self):
        for t in ("help", "yes", "no", "done", "stop"):
            self.assertEqual(bridge.client_message_to_event({"type": t}), (t, {}))

    def test_confirm_tap(self):
        self.assertEqual(
            bridge.client_message_to_event({"type": "confirm_tap", "ok": True}),
            ("confirm_tap", {"ok": True}),
        )

    def test_typed_and_demo_say(self):
        self.assertEqual(
            bridge.client_message_to_event({"type": "typed", "text": "hi"}), ("typed", {"text": "hi"})
        )
        self.assertEqual(
            bridge.client_message_to_event({"type": "demo_say", "variant": "close"}),
            ("demo_say", {"variant": "close"}),
        )

    def test_control_passthrough(self):
        self.assertEqual(bridge.client_message_to_event({"type": "start"}), ("start", {}))


if __name__ == "__main__":
    unittest.main()
