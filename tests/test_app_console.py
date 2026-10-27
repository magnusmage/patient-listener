"""Tests for the therapist console REST API, backed by the real seeded store."""

from __future__ import annotations

import unittest

try:  # the 'api' extra (fastapi) is optional; the stdlib core tests must still run without it.
    from fastapi.testclient import TestClient

    from patient_listener.app.server import create_app
    from patient_listener.config import Settings
    from patient_listener.types import Need

    HAVE_API = True
except Exception:  # pragma: no cover - exercised only when the extra is absent
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "needs the 'api' extra (fastapi)")
class ConsoleApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()
        store = self.client.app.state.pl.store
        store.set_console_user("therapist-sam", "Sam (SLT)", "therapist")
        for pid in self.client.app.state.pl.people.values():
            store.link_console_user("therapist-sam", pid)
        self.client.headers["Authorization"] = "Bearer " + store.issue_console_token("therapist-sam")

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
        self.assertEqual(r.json()["word"]["by"], "therapist-sam")
        self.assertEqual(store.audit_log()[-1]["actor"], "therapist-sam")

    def test_approve_unknown_word_404(self):
        self.assertEqual(
            self.client.post("/api/console/words/margaret/w-missing/approve").status_code, 404
        )

    def identity(self, user, role, people):
        store = self.client.app.state.pl.store
        store.set_console_user(user, user, role)
        for pid in people:
            store.link_console_user(user, pid)
        return {"Authorization": "Bearer " + store.issue_console_token(user)}

    def test_every_console_read_and_approval_requires_authentication(self):
        self.client.headers.pop("Authorization")
        for path in ("me", "caseload", "words/margaret", "grid/margaret",
                     "settings/margaret", "consent/margaret"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get("/api/console/" + path).status_code, 401)
        response = self.client.post("/api/console/words/margaret/w-leo/approve")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_invalid_and_patient_session_tokens_are_rejected(self):
        patient_token = self.client.get(
            "/api/session", headers={"X-PL-Device": "a" * 48}
        ).json()["token"]
        for token in ("made-up", patient_token):
            self.assertEqual(self.client.get("/api/console/caseload", headers={
                "Authorization": "Bearer " + token
            }).status_code, 401)

    def test_caseload_and_patient_routes_are_scoped_to_links(self):
        headers = self.identity("other-slt", "therapist", ["demo-joseph"])
        body = self.client.get("/api/console/caseload", headers=headers).json()
        self.assertEqual([p["id"] for p in body["caseload"]], ["joseph"])
        for path in ("words", "grid", "settings", "consent"):
            for person in ("margaret", "demo-margaret"):
                with self.subTest(path=path, person=person):
                    self.assertEqual(self.client.get(
                        f"/api/console/{path}/{person}", headers=headers
                    ).status_code, 404)
        self.assertEqual(self.client.post(
            "/api/console/words/margaret/w-leo/approve", headers=headers
        ).status_code, 404)

    def test_approval_checks_word_ownership_even_with_access_to_both_people(self):
        store = self.client.app.state.pl.store
        store.add_word_draft("wrong-owner", "demo-margaret", "Rex", "person")
        before = len(store.audit_log())
        response = self.client.post("/api/console/words/joseph/wrong-owner/approve")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(store.audit_log()), before)
        self.assertEqual(store.all_words("demo-margaret")[-1].status.value, "draft")

    def test_carer_cannot_approve_when_therapist_is_linked(self):
        headers = self.identity("carer-alex", "carer", ["demo-margaret"])
        store = self.client.app.state.pl.store
        store.add_word_draft("draft-carer", "demo-margaret", "Rex", "person")
        response = self.client.post(
            "/api/console/words/margaret/draft-carer/approve", headers=headers)
        self.assertEqual(response.status_code, 403)
        caseload = self.client.get("/api/console/caseload", headers=headers).json()
        self.assertFalse(caseload["caseload"][0]["canApprove"])

    def test_carer_can_approve_without_linked_therapist_but_cannot_read_detail_grid(self):
        store = self.client.app.state.pl.store
        store.add_person("person-new", "New person", frozenset({Need.FINDING_WORDS}))
        store.add_word_draft("draft-new", "person-new", "Rex", "person")
        headers = self.identity("carer-alex", "carer", ["person-new"])
        self.assertEqual(self.client.get(
            "/api/console/words/person-new", headers=headers).status_code, 200)
        response = self.client.post(
            "/api/console/words/person-new/draft-new/approve", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["word"]["by"], "carer-alex")
        self.assertEqual(self.client.get(
            "/api/console/grid/person-new", headers=headers).status_code, 403)

    def test_agent_and_patient_roles_cannot_use_console(self):
        for role in ("agent", "patient"):
            headers = self.identity("blocked-" + role, role, ["demo-margaret"])
            self.assertEqual(self.client.get(
                "/api/console/caseload", headers=headers).status_code, 403)
            self.assertEqual(self.client.post(
                "/api/console/words/margaret/w-leo/approve", headers=headers).status_code, 403)

    def test_logout_preserves_token_and_original_expiry(self):
        store = self.client.app.state.pl.store
        before = [dict(row) for row in store._db.execute("SELECT * FROM console_tokens")]
        for _ in range(2):
            self.assertEqual(self.client.post("/api/console/logout").status_code, 200)
            self.assertEqual(self.client.get("/api/console/me").status_code, 200)
        after = [dict(row) for row in store._db.execute("SELECT * FROM console_tokens")]
        self.assertEqual(after, before)

    def test_expiry_and_admin_revocation_still_apply_after_logout(self):
        store = self.client.app.state.pl.store
        self.assertEqual(self.client.post("/api/console/logout").status_code, 200)
        store._db.execute("UPDATE console_tokens SET expires_at='2000-01-01T00:00:00+00:00'")
        store._db.commit()
        self.assertEqual(self.client.get("/api/console/me").status_code, 401)
        self.assertEqual(self.client.post("/api/console/logout").status_code, 401)
        self.client.headers.update(self.identity("replacement", "therapist", ["demo-margaret"]))
        self.assertEqual(self.client.post("/api/console/logout").status_code, 200)
        store.revoke_console_tokens("replacement")
        self.assertEqual(self.client.get("/api/console/me").status_code, 401)

    def test_expired_credentials_and_revoked_credentials_are_rejected(self):
        store = self.client.app.state.pl.store
        store._db.execute("UPDATE console_tokens SET expires_at='2000-01-01T00:00:00+00:00'")
        store._db.commit()
        self.assertEqual(self.client.get("/api/console/me").status_code, 401)
        self.client.headers.update(self.identity("revoked", "therapist", ["demo-margaret"]))
        store.revoke_console_tokens("revoked")
        self.assertEqual(self.client.get("/api/console/me").status_code, 401)

    def test_demo_is_disabled_by_default_even_with_judge_query(self):
        self.assertEqual(self.client.post("/api/console/demo/session?mode=judge").status_code, 404)

    def test_client_cannot_supply_role_or_patient_links(self):
        headers = self.identity("unlinked", "carer", [])
        headers.update({"X-Role": "therapist", "X-User": "therapist-sam"})
        response = self.client.post(
            "/api/console/words/margaret/w-leo/approve?role=therapist", headers=headers,
            json={"role": "therapist", "user_id": "therapist-sam"})
        self.assertEqual(response.status_code, 404)


@unittest.skipUnless(HAVE_API, "needs the 'api' extra (fastapi)")
class DemoConsoleTests(unittest.TestCase):
    def test_judge_credentials_only_access_isolated_demo_store(self):
        with TestClient(create_app(settings=Settings(console_demo_enabled=True))) as client:
            real = client.app.state.pl.store
            demo = client.app.state.pl.console_demo_store
            real.add_person("real-person", "Private", frozenset({Need.FINDING_WORDS}))
            real.add_word_draft("private-word", "real-person", "private", "object")
            demo.add_word_draft("demo-draft", "demo-margaret", "Rex", "person")
            # Same ID in the live database proves the demo cannot change live records.
            real.add_word_draft("demo-draft", "demo-margaret", "Rex", "person")
            response = client.post("/api/console/demo/session")
            self.assertEqual(response.status_code, 200)
            client.headers["Authorization"] = "Bearer " + response.json()["token"]
            self.assertTrue(client.get("/api/console/me").json()["demo"])
            caseload = client.get("/api/console/caseload").json()["caseload"]
            self.assertEqual(len(caseload), 3)
            self.assertNotIn("real-person", [p["id"] for p in caseload])
            self.assertEqual(client.get("/api/console/words/real-person").status_code, 404)
            self.assertEqual(client.post(
                "/api/console/words/margaret/private-word/approve").status_code, 404)
            self.assertEqual(client.post(
                "/api/console/words/margaret/demo-draft/approve").status_code, 200)
            self.assertEqual(next(w for w in real.all_words("demo-margaret")
                                  if w.id == "demo-draft").status.value, "draft")


if __name__ == "__main__":
    unittest.main()
