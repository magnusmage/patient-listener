"""Workbook NFR-07 checks for safe token transport and access logging."""

from __future__ import annotations

import logging
import unittest

from patient_listener.app.access_log import AccessLogRedactionFilter, redact_request_target
from patient_listener.config import Settings

try:
    from fastapi.testclient import TestClient

    from patient_listener.app.server import create_app

    HAVE_API = True
except Exception:  # pragma: no cover - optional API dependency
    HAVE_API = False


class AccessLogTests(unittest.TestCase):
    def test_application_factory_installs_access_log_redaction(self):
        from patient_listener.app.server import create_app

        create_app(Settings())
        filters = logging.getLogger("uvicorn.access").filters
        self.assertTrue(any(isinstance(item, AccessLogRedactionFilter) for item in filters))

    def test_redacts_token_and_device_values(self):
        target = "/ws?token=secret-token&device=browser-device&other=kept"
        redacted = redact_request_target(target)
        self.assertNotIn("secret-token", redacted)
        self.assertNotIn("browser-device", redacted)
        self.assertIn("other=kept", redacted)

    def test_websocket_scope_is_redacted_before_acceptance_logging(self):
        from patient_listener.app.server import _redact_websocket_scope

        scope = {"query_string": b"token=secret-token&device=browser-device&other=kept"}
        _redact_websocket_scope(scope)
        text = scope["query_string"].decode("utf-8")
        self.assertNotIn("secret-token", text)
        self.assertNotIn("browser-device", text)
        self.assertIn("other=kept", text)

    def test_uvicorn_filter_changes_the_request_target_before_formatting(self):
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1", "GET", "/ws?token=secret", "1.1", 101), None,
        )
        self.assertTrue(AccessLogRedactionFilter().filter(record))
        self.assertNotIn("secret", record.args[2])


class ProductionSettingsTests(unittest.TestCase):
    def test_production_requires_a_stable_session_secret(self):
        with self.assertRaises(ValueError):
            Settings(environment="production", require_https=True).assert_safe_startup()

    def test_production_requires_https_and_a_fifteen_minute_lifetime(self):
        with self.assertRaises(ValueError):
            Settings(environment="production", session_token_secret="secret", require_https=False).assert_safe_startup()
        with self.assertRaises(ValueError):
            Settings(
                environment="production", session_token_secret="secret", require_https=True,
                session_token_ttl_s=60,
            ).assert_safe_startup()


@unittest.skipUnless(HAVE_API, "needs the 'api' extra (fastapi)")
class HttpsTransportTests(unittest.TestCase):
    def setUp(self):
        settings = Settings(
            environment="production", session_token_secret="unit-secret", require_https=True,
            trust_proxy_headers=True, database_url="postgresql://transport-test-unused",
        )
        from unittest.mock import patch
        from patient_listener.store.sqlite_store import SqliteStore
        database = patch('patient_listener.app.deps.open_store',
                         side_effect=lambda *a, **kw: SqliteStore(check_same_thread=False))
        database.start()
        self.addCleanup(database.stop)
        self.client = TestClient(create_app(settings))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_session_token_endpoint_rejects_plain_http(self):
        response = self.client.get("/api/session", headers={"X-PL-Device": "a" * 48})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "HTTPS is required")

    def test_session_token_endpoint_accepts_https_from_the_deployment_proxy(self):
        response = self.client.get(
            "/api/session",
            headers={"X-PL-Device": "a" * 48, "X-Forwarded-Proto": "https"},
        )
        self.assertEqual(response.status_code, 200)

    def test_session_token_endpoint_does_not_trust_spoofable_headers_by_default(self):
        settings = Settings(environment="production", session_token_secret="unit-secret", require_https=True,
                            database_url="postgresql://transport-test-unused")
        with TestClient(create_app(settings)) as client:
            response = client.get(
                "/api/session",
                headers={"X-PL-Device": "a" * 48, "X-Forwarded-Proto": "https"},
            )
        self.assertEqual(response.status_code, 400)
