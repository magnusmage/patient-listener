"""Tests for the in-process one-active-session guard."""

from __future__ import annotations

import unittest

from patient_listener.app.session_registry import SessionRegistry


class SessionRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_blocks_another_session_for_the_same_person(self):
        registry = SessionRegistry()
        self.assertTrue(await registry.claim("person-1"))
        self.assertFalse(await registry.claim("person-1"))
        self.assertTrue(await registry.claim("person-2"))

    async def test_release_allows_reconnection(self):
        registry = SessionRegistry()
        await registry.claim("person-1")
        await registry.release("person-1")
        self.assertTrue(await registry.claim("person-1"))
