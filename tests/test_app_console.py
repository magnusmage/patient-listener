"""Tests for the therapist console REST API, backed by the real seeded store."""

from __future__ import annotations

import unittest

try:  # the 'api' extra (fastapi) is optional; the stdlib core tests must still run without it.
    from fastapi.testclient import TestClient

    from patient_listener.app.server import create_app

    HAVE_API = True
except Exception:  # pragma: no cover - exercised only when the extra is absent
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "needs the 'api' extra (fastapi)")
class ConsoleApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_caseload_lists_seeded_personas(self):
        body = self.client.get("/api/console/caseload").json()
        names = {p["name"] for p in body["caseload"]}
        self.assertEqual(names, {"Margaret", "Daniyal", "Joseph"})

    def test_words_for_margaret(self):
        body = self.client.get("/api/console/words/margaret").json()
        texts = {w["text"] for w in body["words"]}
        self.assertIn("Leo", texts)
        self.assertIn("kettle", texts)

    def test_words_accepts_full_person_id(self):
        r = self.client.get("/api/console/words/demo-margaret")
        self.assertEqual(r.status_code, 200)

    def test_unknown_person_404(self):
        self.assertEqual(self.client.get("/api/console/words/nobody").status_code, 404)

    def test_settings_report_merged_config(self):
        body = self.client.get("/api/console/settings/margaret").json()
        self.assertEqual(body["hintOrder"], "meaning-first")
        self.assertEqual(body["hintWait"], 7)
        self.assertEqual(body["sessionMin"], 20)

    def test_grid_shape(self):
        body = self.client.get("/api/console/grid/margaret").json()
        self.assertEqual(len(body["days"]), 5)
        self.assertTrue(all(len(r["cells"]) == 5 for r in body["rows"]))

    def test_approve_word_flips_status(self):
        # Seed a draft via the store, then approve it through the API.
        store = self.client.app.state.pl.store
        store.add_word_draft("w-new", "demo-margaret", "Rex", "person", meaning_cue="the puppy")
        before = next(w for w in self.client.get("/api/console/words/margaret").json()["words"] if w["id"] == "w-new")
        self.assertEqual(before["status"], "draft")

        r = self.client.post("/api/console/words/margaret/w-new/approve")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["word"]["status"], "approved")

    def test_approve_unknown_word_404(self):
        self.assertEqual(
            self.client.post("/api/console/words/margaret/w-missing/approve").status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
