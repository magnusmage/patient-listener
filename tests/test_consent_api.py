"""Authenticated consent recording: explicit choices, scoping and durable history."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.config import Settings
from patient_listener.store.sqlite_store import SqliteStore


class ConsentTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(Settings(ai_enabled=False, voice_enabled=False,
            nebius_api_key='', console_demo_enabled=False)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.client.app.state.pl.store
        self.slt = self.identity('sam', 'therapist', 'demo-margaret')
        self.carer = self.identity('alex', 'carer', 'demo-margaret')

    def identity(self, name, role, person):
        self.store.set_console_user(name, name, role)
        self.store.link_console_user(name, person)
        return {'Authorization': 'Bearer ' + self.store.issue_console_token(name)}

    def update(self, body, headers=None):
        return self.client.patch('/api/console/consent/margaret', json=body,
            headers=self.slt if headers is None else headers)

    def events(self):
        return self.store._db.execute('SELECT * FROM consent_events ORDER BY id').fetchall()

    def test_explicit_choices_and_withdrawal_keep_history(self):
        response = self.update({'personConfirmed': True, 'tellCarerLowMood': True,
                               'shareWithTherapist': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertTrue(response.json()['tellCarerLowMood'])
        self.assertFalse(response.json()['dataSharing'])
        self.assertEqual(self.update({'personConfirmed': True, 'tellCarerLowMood': False},
                                    self.carer).status_code, 200)
        self.assertFalse(self.store.has_consent('demo-margaret', 'tell_carer_low_mood'))
        self.assertTrue(self.store.has_consent('demo-margaret', 'share_with_therapist'))
        events = self.events()
        self.assertEqual(len(events), 3)
        self.assertEqual([r['actor'] for r in events], ['sam', 'sam', 'alex'])
        self.assertEqual([r['granted'] for r in events], [1, 1, 0])
        self.assertEqual(self.store.audit_log()[-1]['detail'], 'demo-margaret')

    def test_invalid_requests_do_not_write(self):
        for body in [{}, {'personConfirmed': True}, {'dataSharing': True},
            {'personConfirmed': False, 'dataSharing': True},
            {'personConfirmed': 1, 'dataSharing': True},
            {'personConfirmed': True, 'dataSharing': None},
            {'personConfirmed': True, 'dataSharing': 'true'},
            {'personConfirmed': True, 'dataSharing': 1},
            {'personConfirmed': True, 'actor': 'sam', 'dataSharing': True}]:
            with self.subTest(body=body):
                self.assertEqual(self.update(body).status_code, 422)
        self.assertEqual(len(self.events()), 0)

    def test_authentication_and_links_are_enforced(self):
        body = {'personConfirmed': True, 'dataSharing': True}
        self.assertEqual(self.update(body, {}).status_code, 401)
        other = self.identity('other', 'therapist', 'demo-joseph')
        agent = self.identity('agent', 'agent', 'demo-margaret')
        self.assertEqual(self.update(body, other).status_code, 404)
        self.assertEqual(self.update(body, agent).status_code, 403)
        for actor in ('other', 'agent'):
            with self.assertRaises(PermissionError):
                self.store.console_update_consent('demo-margaret', {'data_sharing': True},
                                                 actor=actor, person_confirmed=True)
        self.assertEqual(len(self.events()), 0)

    def test_transaction_rolls_back_if_history_write_fails(self):
        self.store._db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON consent_events BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(Exception):
            self.store.console_update_consent('demo-margaret', {'data_sharing': True},
                                             actor='sam', person_confirmed=True)
        self.assertFalse(self.store.has_consent('demo-margaret', 'data_sharing'))
        self.assertEqual(len(self.events()), 0)

    def test_reopen_keeps_current_choices_and_events(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'consent.db')
            store = SqliteStore(path)
            from patient_listener.tools.seed import seed_all
            seed_all(store)
            store.set_console_user('sam', 'Sam', 'therapist')
            store.link_console_user('sam', 'demo-margaret')
            store.console_update_consent('demo-margaret', {'data_sharing': True},
                                         actor='sam', person_confirmed=True)
            store.close()
            store = SqliteStore(path)
            try:
                self.assertTrue(store.has_consent('demo-margaret', 'data_sharing'))
                self.assertEqual(store._db.execute('SELECT COUNT(*) FROM consent_events').fetchone()[0], 1)
            finally:
                store.close()
