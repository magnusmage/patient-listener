"""Credential storage and authorization must survive a process restart."""

import tempfile
import unittest
from pathlib import Path

from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.types import Need


class ConsoleCredentialTests(unittest.TestCase):
    def test_credentials_and_links_persist_without_storing_plaintext_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "console.db")
            store = SqliteStore(path)
            store.add_person("p1", "Person", frozenset({Need.FINDING_WORDS}))
            store.set_console_user("slt1", "Therapist", "therapist")
            store.link_console_user("slt1", "p1")
            token = store.issue_console_token("slt1")
            hashes = [r["token_hash"] for r in store._db.execute("SELECT token_hash FROM console_tokens")]
            self.assertNotIn(token, hashes)
            self.assertTrue(all(len(h) == 64 for h in hashes))
            store.close()
            store = SqliteStore(path)
            try:
                self.assertEqual(store.console_user_for_token(token)["id"], "slt1")
                self.assertEqual(store.linked_people("slt1"), ["p1"])
                store.set_console_user("slt1", "Therapist", "carer")
                self.assertIsNone(store.console_user_for_token(token))
            finally:
                store.close()

    def test_deleting_patient_removes_access_link(self):
        store = SqliteStore()
        try:
            store.add_person("p1", "Person", frozenset({Need.FINDING_WORDS}))
            store.set_console_user("slt1", "Therapist", "therapist")
            store.link_console_user("slt1", "p1")
            store.delete_all("p1")
            with self.assertRaises(ValueError):
                store.add_person("p1", "Another person", frozenset({Need.FINDING_WORDS}))
            self.assertEqual(store.linked_people("slt1"), [])
        finally:
            store.close()

    def test_store_approval_cannot_bypass_roles_or_ownership(self):
        store = SqliteStore()
        try:
            for pid in ("p1", "p2"):
                store.add_person(pid, "Person", frozenset({Need.FINDING_WORDS}))
            store.add_word_draft("word", "p1", "kettle", "object")
            store.set_console_user("agent1", "Agent", "agent")
            store.link_console_user("agent1", "p1")
            with self.assertRaises(PermissionError):
                store.console_approve_word("p1", "word", "agent1")
            store.set_console_user("slt1", "Therapist", "therapist")
            store.link_console_user("slt1", "p2")
            with self.assertRaises(KeyError):
                store.console_approve_word("p2", "word", "slt1")
            self.assertEqual(store.all_words("p1")[0].status.value, "draft")
        finally:
            store.close()
