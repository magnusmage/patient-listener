"""Store: drafts, approval, attempt logging, export, delete-all, row isolation, kill switch
(FR-40, FR-60, FR-62, FR-63, FR-84, NFR-06, NFR-07)."""

from __future__ import annotations

import unittest

from patient_listener.schemas import Attempt
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.types import HintLevel, Need, Outcome, WordStatus


class TestStore(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore()  # in-memory
        self.store.add_person("p1", "Margaret", frozenset({Need.FINDING_WORDS}))
        self.store.add_person("p2", "Joseph", frozenset({Need.BEING_HEARD}))

    def test_draft_then_approve(self):
        self.store.add_word_draft("w1", "p1", "Biscuit", "person", "Leo's puppy")
        self.assertEqual(self.store.words("p1"), [])  # drafts are not live (FR-40)
        self.store.approve_word("w1", by="slt")
        live = self.store.words("p1")
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0].status, WordStatus.APPROVED)
        self.assertEqual(live[0].approved_by, "slt")

    def test_row_isolation(self):
        self.store.add_word_draft("w1", "p1", "Biscuit", "person")
        self.store.approve_word("w1", "slt")
        self.assertEqual(len(self.store.words("p1")), 1)
        self.assertEqual(self.store.words("p2"), [])  # p2 cannot see p1's words

    def test_log_attempt_no_text(self):
        self.store.add_word_draft("w1", "p1", "Leo", "person")
        self.store.approve_word("w1", "slt")
        self.store.log_attempt(
            Attempt(
                session_id="s",
                word_id="w1",
                hint_level=HintLevel.MEANING,
                outcome=Outcome.FOUND,
                seconds_to_find=9.4,
                match_score=0.95,
                confirmed=True,
            )
        )
        rows = self.store.attempts_for("p1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0].keys()) & {"text", "transcript", "audio"}, set())

    def test_export_csv_includes_phrases(self):
        self.store.add_word_draft("p-1", "p1", "Can you open the window?", "phrase")
        self.store.approve_word("p-1", "slt")
        csv_text = self.store.export_csv("p1")
        self.assertIn("phrase", csv_text)
        self.assertIn("Can you open the window?", csv_text)

    def test_delete_all(self):
        self.store.add_word_draft("w1", "p1", "Leo", "person")
        self.store.approve_word("w1", "slt")
        result = self.store.delete_all("p1")
        self.assertTrue(result["deleted"])
        self.assertEqual(self.store.all_words("p1"), [])
        self.assertEqual(self.store.person_name("p1"), "p1")  # gone -> id echoed

    def test_kill_switch(self):
        self.assertTrue(self.store.is_ai_enabled())
        self.store.set_ai_enabled(False, reason="demo rehearsal")
        self.assertFalse(self.store.is_ai_enabled())
        self.store.set_ai_enabled(True)
        self.assertTrue(self.store.is_ai_enabled())

    def test_audit_log_records_approval(self):
        self.store.add_word_draft("w1", "p1", "Leo", "person")
        self.store.approve_word("w1", "slt")
        actions = [a["action"] for a in self.store.audit_log()]
        self.assertIn("approve_word", actions)


if __name__ == "__main__":
    unittest.main()
