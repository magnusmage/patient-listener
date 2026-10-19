"""End-to-end tests for the app server over a real (in-process) WebSocket.

Uses FastAPI's TestClient, which runs the app exactly as uvicorn would. These exercise the
*real* decision core driven through the server: a found word is decided by the matcher, a
safety stop by the safety rules - nothing is re-implemented here.
"""

from __future__ import annotations

import unittest

try:  # the 'api' extra (fastapi) is optional; the stdlib core tests must still run without it.
    from fastapi.testclient import TestClient

    from patient_listener.app.server import create_app

    HAVE_API = True
except Exception:  # pragma: no cover - exercised only when the extra is absent
    HAVE_API = False


def _drain_until(ws, want_type, limit=12):
    """Read events until one with ``type == want_type`` arrives; return all collected."""
    got = []
    for _ in range(limit):
        ev = ws.receive_json()
        got.append(ev)
        if ev.get("type") == want_type:
            return got
    raise AssertionError(f"never saw {want_type!r}; got {[e.get('type') for e in got]}")


@unittest.skipUnless(HAVE_API, "needs the 'api' extra (fastapi)")
class HttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()  # trigger lifespan (seed the store)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])

    def test_session_token_issued(self):
        r = self.client.get("/api/session", params={"person": "margaret"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("token", body)
        self.assertTrue(body["ws_url"].endswith("/ws"))
        self.assertEqual(body["needs"], ["finding_words"])

    def test_unknown_person_404(self):
        self.assertEqual(self.client.get("/api/session", params={"person": "nobody"}).status_code, 404)

    def test_ws_rejects_bad_token(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws?token=not-a-real-token"):
                pass


@unittest.skipUnless(HAVE_API, "needs the 'api' extra (fastapi)")
class SessionFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()
        token = self.client.get("/api/session", params={"person": "margaret"}).json()["token"]
        self._ws = self.client.websocket_connect(f"/ws?token={token}")
        self.ws = self._ws.__enter__()

    def tearDown(self):
        self._ws.__exit__(None, None, None)
        self.client.__exit__(None, None, None)

    def test_start_greets_and_prompts(self):
        self.ws.send_json({"type": "start"})
        events = _drain_until(self.ws, "prompt")
        types = [e["type"] for e in events]
        self.assertIn("greeting", types)
        prompt = next(e for e in events if e["type"] == "prompt")
        self.assertEqual(prompt["profile"], "finding_words")
        self.assertEqual(prompt["feedback"], "word_found")

    def test_close_word_confirms_then_yes_finds_and_logs(self):
        self.ws.send_json({"type": "start"})
        _drain_until(self.ws, "prompt")

        # A near-miss: the real matcher scores it in the 0.60-0.89 band -> a confirm step.
        self.ws.send_json({"type": "demo_say", "variant": "close"})
        confirm = _drain_until(self.ws, "confirm")[-1]
        self.assertEqual(confirm["word"], "Biscuit")  # Margaret's first word by id

        # Confirming yes -> the controller logs one attempt and praises.
        self.ws.send_json({"type": "yes"})
        found_events = _drain_until(self.ws, "found")
        types = [e["type"] for e in found_events]
        self.assertIn("attempt", types)
        found = next(e for e in found_events if e["type"] == "found")
        self.assertEqual(found["word"], "Biscuit")
        attempt = next(e for e in found_events if e["type"] == "attempt")
        self.assertEqual(attempt["outcome"], "found")

    def test_exact_word_is_found_without_confirm(self):
        self.ws.send_json({"type": "start"})
        _drain_until(self.ws, "prompt")
        self.ws.send_json({"type": "demo_say", "variant": "exact"})
        found = _drain_until(self.ws, "found")[-1]
        self.assertEqual(found["word"], "Biscuit")

    def test_stroke_phrase_triggers_safety(self):
        self.ws.send_json({"type": "start"})
        _drain_until(self.ws, "prompt")
        self.ws.send_json({"type": "demo_say", "variant": "stroke"})
        safety = _drain_until(self.ws, "safety")[-1]
        self.assertEqual(safety["card"], "stroke_signs")
        self.assertEqual(safety["number"], "999")

    def test_help_advances_hint_ladder(self):
        self.ws.send_json({"type": "start"})
        _drain_until(self.ws, "prompt")
        self.ws.send_json({"type": "help"})
        hint = _drain_until(self.ws, "hint")[-1]
        self.assertEqual(hint["level"], 1)  # meaning first


if __name__ == "__main__":
    unittest.main()
