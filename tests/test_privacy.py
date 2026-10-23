"""Privacy operations use disposable stores and synthetic people only."""
import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from patient_listener.app.server import create_app
from patient_listener.config import Settings
from patient_listener.schemas import Attempt
from patient_listener.store.privacy import PrivacyStore, PrivacyConflict, _two_years, person_key
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.types import HintLevel, Outcome

PID = 'demo-margaret'


class PrivacyStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore(ai_enabled=False)
        self.addCleanup(self.store.close)
        seed_all(self.store)
        for user, role in [('sam', 'therapist'), ('alex', 'carer')]:
            self.store.set_console_user(user, user, role)
            self.store.link_console_user(user, PID)
        self.privacy = PrivacyStore(self.store)

    def delete(self, actor='sam'):
        challenge = self.privacy.request_deletion(PID, actor)
        return self.privacy.confirm_deletion(PID, actor, challenge['confirmation_token'], person_confirmed=True)

    def test_csv_includes_phrases_attempts_schedule_and_consent_without_credentials(self):
        self.store.add_word_draft('phrase', PID, 'Can you open the window?', 'phrase')
        self.store.log_attempt(Attempt('s', 'w-leo', HintLevel.NONE, Outcome.FOUND, 2, 1, True))
        self.store.console_update_consent(PID, {'data_sharing': True}, actor='sam', person_confirmed=True)
        token = self.store.issue_console_token('sam')
        data = self.privacy.export(PID, 'alex', person_confirmed=True)
        rows = list(csv.DictReader(io.StringIO(data)))
        types = {row['type'] for row in rows}
        self.assertTrue({'person', 'profile', 'needs', 'word', 'phrase', 'attempt', 'schedule', 'consent', 'consent_evidence'} <= types)
        self.assertIn('Can you open the window?', data)
        self.assertNotIn(token, data)
        self.assertNotIn('Joseph', data)
        self.assertNotIn('session_id', data)
        self.assertEqual(self.store.audit_log()[-1]['action'], 'export_person_data')

    def test_csv_formula_characters_are_escaped_and_unicode_preserved(self):
        self.store.add_word_draft('formula', PID, '=HYPERLINK("bad")', 'phrase')
        self.store.add_word_draft('unicode', PID, 'Café please', 'phrase')
        rows = list(csv.DictReader(io.StringIO(self.privacy.export(PID, 'sam', person_confirmed=True))))
        self.assertEqual(next(r['text'] for r in rows if r['id'] == 'formula'), "'=HYPERLINK(\"bad\")")
        self.assertEqual(next(r['text'] for r in rows if r['id'] == 'unicode'), 'Café please')

    def test_confirmation_is_hashed_expiring_and_bound_to_actor_person(self):
        challenge = self.privacy.request_deletion(PID, 'sam')
        token = challenge['confirmation_token']
        saved = self.store._db.execute('SELECT * FROM privacy_challenges').fetchone()
        self.assertEqual(saved['token_hash'], person_key(token))
        self.assertNotEqual(saved['token_hash'], token)
        for pid, actor in [(PID, 'alex'), ('demo-joseph', 'sam')]:
            with self.assertRaises((KeyError, ValueError)):
                self.privacy.confirm_deletion(pid, actor, token, person_confirmed=True)
        with self.assertRaises(ValueError):
            self.privacy.confirm_deletion(PID, 'sam', token, person_confirmed=False)
        self.store._db.execute("UPDATE privacy_challenges SET expires_at='2000-01-01T00:00:00+00:00'")
        self.store._db.commit()
        with self.assertRaises(ValueError):
            self.privacy.confirm_deletion(PID, 'sam', token, person_confirmed=True)
        self.assertTrue(self.store.person_exists(PID))

    def test_new_confirmation_invalidates_previous_token(self):
        old = self.privacy.request_deletion(PID, 'sam')['confirmation_token']
        self.privacy.request_deletion(PID, 'sam')
        with self.assertRaises(ValueError):
            self.privacy.confirm_deletion(PID, 'sam', old, person_confirmed=True)

    def test_delete_removes_scoped_data_retains_consent_and_preserves_other_people(self):
        self.store.console_update_consent(PID, {'data_sharing': True}, actor='sam', person_confirmed=True)
        self.store.log_attempt(Attempt('s', 'w-leo', HintLevel.NONE, Outcome.FOUND, 2, 1, True))
        self.store.set_console_user('hermes', 'Hermes', 'agent')
        self.store.link_console_user('hermes', PID)
        from patient_listener.store.agent_store import AgentStore
        agent = AgentStore(self.store)
        token = agent.issue_token('hermes', 'alex', PID)
        self.store.link_console_user('sam', 'demo-joseph')
        self.store.add_word_draft('other', 'demo-joseph', 'Hello', 'phrase')
        self.store.console_update_consent('demo-joseph', {'data_sharing': True}, actor='sam', person_confirmed=True)
        result = self.delete()
        self.assertTrue(result['deleted'])
        self.assertFalse(self.store.person_exists(PID))
        self.assertEqual(self.store.all_words(PID), [])
        self.assertEqual(self.store.attempts_for(PID), [])
        self.assertEqual(self.store.all_cards(PID), {})
        self.assertEqual(self.store.linked_people('sam'), ['demo-joseph'])
        self.assertEqual(len(self.store.all_words('demo-joseph')), 1)
        self.assertIsNotNone(self.store.console_identity('sam'))
        self.assertFalse(self.store.is_ai_enabled())
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM agent_credentials WHERE person_id=?', (PID,)).fetchone()[0], 0)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM consent_events WHERE person_id=?', (PID,)).fetchone()[0], 1)
        self.assertFalse(result['consent_evidence_purged'])
        future = datetime.fromisoformat(result['consent_evidence_retained_until'])
        self.assertEqual(self.privacy.purge_expired_consent(future - timedelta(seconds=1))['consent_events_deleted'], 0)
        self.assertEqual(self.privacy.purge_expired_consent(future)['consent_events_deleted'], 1)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM consent_events').fetchone()[0], 1)
        self.assertTrue(self.privacy.receipt(result['receipt_id'], 'sam')['consent_evidence_purged'])
        self.assertEqual(self.privacy.purge_expired_consent(future)['consent_events_deleted'], 0)

    def test_failure_rolls_back_deletion_and_keeps_challenge_usable(self):
        self.store._db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON deleted_people BEGIN SELECT RAISE(ABORT, 'test'); END")
        challenge = self.privacy.request_deletion(PID, 'sam')['confirmation_token']
        with self.assertRaises(Exception):
            self.privacy.confirm_deletion(PID, 'sam', challenge, person_confirmed=True)
        self.assertTrue(self.store.person_exists(PID))
        self.assertEqual(len(self.store.all_words(PID)), 4)
        self.assertIn(PID, self.store.linked_people('sam'))
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM privacy_challenges').fetchone()[0], 1)
        self.store._db.execute('DROP TRIGGER reject_receipt')
        self.store._db.commit()
        self.assertTrue(self.privacy.confirm_deletion(PID, 'sam', challenge, person_confirmed=True)['deleted'])

    def test_photo_reference_blocks_false_completion_without_partial_deletion(self):
        self.store._db.execute("UPDATE words SET photo_id='synthetic-photo' WHERE id='w-leo'")
        self.store._db.commit()
        with self.assertRaises(PrivacyConflict):
            self.delete()
        self.assertTrue(self.store.person_exists(PID))
        self.assertEqual(len(self.store.all_words(PID)), 4)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM deleted_people').fetchone()[0], 0)

    def test_reopen_does_not_reseed_deleted_person_and_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'synthetic.db')
            s = SqliteStore(path); seed_all(s)
            s.set_console_user('sam', 'Sam', 'therapist'); s.link_console_user('sam', PID)
            p = PrivacyStore(s)
            token = p.request_deletion(PID, 'sam')['confirmation_token']
            receipt = p.confirm_deletion(PID, 'sam', token, person_confirmed=True)
            s.close()
            s = SqliteStore(path)
            try:
                self.assertNotIn('margaret', seed_all(s))
                p = PrivacyStore(s)
                self.assertEqual(p.confirm_deletion(PID, 'sam', token, person_confirmed=True)['receipt_id'], receipt['receipt_id'])
                with self.assertRaises(KeyError): p.receipt(receipt['receipt_id'], 'alex')
                with self.assertRaises(ValueError): s.add_person(PID, 'Margaret', frozenset())
                with self.assertRaises(KeyError): s.add_word_draft('stale', PID, 'Hi', 'phrase')
            finally: s.close()


    def test_audit_history_retains_accountability_without_raw_patient_word_references(self):
        self.store.console_add_word_draft(PID, actor='sam', text='Hello', kind='phrase')
        self.store._db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
            ('sam', 'synthetic_other', 'demo-joseph', datetime.now(timezone.utc).isoformat()))
        self.store._db.commit()
        self.delete()
        rows = self.store.audit_log()
        self.assertTrue(any(r['action'] == 'delete_person_data' for r in rows))
        self.assertTrue(any(r['detail'] == 'demo-joseph' for r in rows))
        self.assertFalse(any(PID in r['detail'] or r['detail'] == 'w-leo' for r in rows))
        self.assertTrue(any(r['detail'] == 'deleted:'+person_key(PID) for r in rows))
        result = self.privacy.purge_expired_consent(datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year+3))
        self.assertGreater(result['audit_events_deleted'], 0)

    def test_leap_day_retention_is_two_calendar_years(self):
        self.assertEqual(_two_years(datetime(2024, 2, 29, tzinfo=timezone.utc)), datetime(2026, 2, 28, tzinfo=timezone.utc))

    def test_deleted_person_does_not_receive_new_nightly_rows(self):
        self.delete()
        from patient_listener.app.nightly_worker import NightlyWorker
        cfg = Settings(nightly_enabled=True, nightly_actor_id='sam', nightly_people=('margaret',), nightly_time='00:00', nightly_timezone='UTC')
        state = SimpleNamespace(store=self.store, people={'margaret': PID})
        app = SimpleNamespace(state=SimpleNamespace(pl=state, settings=cfg))
        self.assertEqual(asyncio.run(NightlyWorker(app).run_due(datetime.now(timezone.utc))), [])
        self.assertEqual(self.store.nightly_runs(PID), [])


class PrivacyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(Settings(ai_enabled=False, voice_enabled=False, nebius_api_key='', console_demo_enabled=True)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.client.app.state.pl.store
        self.sam = self.identity('sam', 'therapist', PID)
        self.alex = self.identity('alex', 'carer', PID)

    def identity(self, name, role, pid):
        self.store.set_console_user(name, name, role)
        self.store.link_console_user(name, pid)
        return {'Authorization': 'Bearer ' + self.store.issue_console_token(name)}

    def challenge(self, headers=None):
        return self.client.post('/api/console/privacy/margaret/deletion-request', headers=headers or self.sam)

    def confirm(self, token, headers=None, person='margaret'):
        return self.client.request('DELETE', '/api/console/privacy/' + person, headers=headers or self.sam,
            json={'personConfirmed': True, 'confirmationToken': token})

    def test_export_requires_auth_link_explicit_confirmation_and_blocks_demo_agent(self):
        path = '/api/console/privacy/margaret/export'
        body = {'personConfirmed': True}
        other = self.identity('other', 'therapist', 'demo-joseph')
        agent = self.identity('agent', 'agent', PID)
        demo = self.client.post('/api/console/demo/session').json()['token']
        for headers, code in [({}, 401), (other, 404), (agent, 403), ({'Authorization': 'Bearer '+demo}, 403)]:
            self.assertEqual(self.client.post(path, json=body, headers=headers).status_code, code)
        for body in [{}, {'personConfirmed': False}, {'personConfirmed': 'true'}, {'personConfirmed': 1}, {'personConfirmed': True, 'actor': 'sam'}]:
            self.assertEqual(self.client.post(path, json=body, headers=self.sam).status_code, 422)
        response = self.client.post(path, json={'personConfirmed': True}, headers=self.alex)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('attachment', response.headers['content-disposition'])

    def test_delete_requires_second_confirmation_and_receipt_survives_unlinking(self):
        response = self.challenge()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.store.person_exists(PID))
        token = response.json()['confirmation_token']
        self.assertEqual(self.confirm(token, self.alex).status_code, 422)
        result = self.confirm(token)
        self.assertEqual(result.status_code, 200)
        receipt = result.json()['receipt_id']
        self.assertEqual(self.confirm(token).json()['receipt_id'], receipt)
        self.assertEqual(self.client.get('/api/console/deletions/'+receipt, headers=self.sam).status_code, 200)
        self.assertEqual(self.client.get('/api/console/deletions/'+receipt, headers=self.alex).status_code, 404)
        self.assertEqual(self.client.get('/api/session?person=margaret&device=privacy-test-device').status_code, 404)

    def test_active_session_blocks_export_and_delete_without_removal(self):
        state = self.client.app.state.pl
        self.client.portal.call(state.sessions.claim, PID)
        try:
            self.assertEqual(self.challenge().status_code, 409)
            self.assertEqual(self.client.post('/api/console/privacy/margaret/export', headers=self.sam, json={'personConfirmed': True}).status_code, 409)
        finally: self.client.portal.call(state.sessions.release, PID)
        self.assertTrue(self.store.person_exists(PID))
        self.assertEqual(self.challenge().status_code, 200)

    def test_signed_patient_token_is_rejected_after_deletion(self):
        device = 'a' * 32
        token = self.client.app.state.pl.signer.issue(PID, device)
        challenge = self.challenge().json()['confirmation_token']
        self.assertEqual(self.confirm(challenge).status_code, 200)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws?token='+token+'&device='+device):
                self.fail('Deleted person must not connect')

    def test_failure_response_never_confirms_deletion(self):
        token = self.challenge().json()['confirmation_token']
        with patch.object(PrivacyStore, '_delete', side_effect=RuntimeError('private database contents')):
            result = self.confirm(token)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('private database contents', result.text)
        self.assertTrue(self.store.person_exists(PID))
