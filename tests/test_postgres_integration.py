"""Opt-in destructive tests for the explicitly named LOCAL Docker test database only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest

URL=os.environ.get('PL_TEST_POSTGRES_URL')


@unittest.skipUnless(URL,'Set PL_TEST_POSTGRES_URL for the disposable local PostgreSQL test DB')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        from patient_listener.store.postgres_store import PostgresConnection,postgres_url,PostgresStore
        from patient_listener.store.transfer import TABLES,quoted
        url=postgres_url(URL)
        if url.host not in {'127.0.0.1','localhost'} or url.database!='pltest':
            raise RuntimeError('Refusing destructive tests outside local pltest database')
        connection=PostgresConnection(URL)
        try:
            with connection:connection.execute('TRUNCATE '+','.join(map(quoted,TABLES))+' RESTART IDENTITY')
        finally:connection.close()
        self.store=PostgresStore(URL,ai_enabled=False)
        self.addCleanup(self.store.close)
        from patient_listener.tools.seed import seed_all
        seed_all(self.store)
        for user,role in (('sam','therapist'),('alex','carer'),('hermes','agent')):
            self.store.set_console_user(user,user,role);self.store.link_console_user(user,'demo-margaret')

    def test_attempt_and_fsrs_card_commit_together(self):
        from unittest.mock import patch
        from patient_listener.schemas import Attempt
        from patient_listener.types import HintLevel, Outcome
        from patient_listener.schedule.fsrs import Card
        attempt = Attempt('fsrs-test', 'w-leo', HintLevel.NONE, Outcome.FOUND, 2, 1, True)
        before = len(self.store.attempts_for('demo-margaret'))
        with patch.object(self.store, '_write_card', side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):
                self.store.log_attempt(attempt)
        self.assertEqual(len(self.store.attempts_for('demo-margaret')), before)
        self.assertIsNone(self.store.get_card('demo-margaret', 'w-leo'))
        self.store.log_attempt(attempt)
        card = Card.from_json(self.store.get_card('demo-margaret', 'w-leo'))
        self.assertEqual(card.native.last_review, attempt.at)
        self.assertGreater(card.due_dt(), attempt.at)
        self.assertEqual(len(self.store.attempts_for('demo-margaret')), before + 1)

    def test_auth_drafts_profiles_and_consent_use_real_postgres(self):
        token=self.store.issue_console_token('sam')
        self.assertEqual(self.store.console_user_for_token(token)['id'],'sam')
        draft=self.store.console_add_word_draft('demo-margaret',actor='alex',text='Milo',kind='person')
        with self.assertRaises(PermissionError):self.store.console_approve_word('demo-margaret',draft.id,'alex')
        self.store.console_approve_word('demo-margaret',draft.id,'sam')
        self.store.console_update_profile('demo-margaret',{'max_wait_s':30},actor='sam')
        self.assertEqual(self.store.person_pause('demo-margaret').max_wait_s,30)
        self.store.console_update_consent('demo-margaret',{'tell_carer_low_mood':True},actor='sam',person_confirmed=True)
        self.assertTrue(self.store.has_consent('demo-margaret','tell_carer_low_mood'))
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM consent_events').fetchone()[0],1)

    def test_two_store_instances_share_data(self):
        from patient_listener.store.postgres_store import PostgresStore
        other=PostgresStore(URL,ai_enabled=True)
        try:
            self.assertFalse(other.is_ai_enabled())
            self.store.set_ai_enabled(True)
            self.assertTrue(other.is_ai_enabled())
            self.store.console_add_word_draft('demo-margaret',actor='sam',text='Milo',kind='person')
            self.assertTrue(any(w.text=='Milo' for w in other.all_words('demo-margaret')))
        finally:other.close()

    def test_competing_nightly_reservations_cannot_exceed_daily_budget(self):
        from patient_listener.store.postgres_store import PostgresStore
        other=PostgresStore(URL)
        try:
            with ThreadPoolExecutor(2) as pool:
                one=pool.submit(self.store.claim_nightly,'2026-10-22','one','sam',1,1)
                two=pool.submit(other.claim_nightly,'2026-10-22','two','sam',1,1)
                self.assertEqual(one.result()+two.result(),1)
            self.assertIsNone(other.claim_nightly('2026-10-22','one','sam',1,1))
        finally:other.close()

    def test_agent_retries_across_workers_create_only_one_draft(self):
        from patient_listener.store.postgres_store import PostgresStore
        from patient_listener.store.agent_store import AgentStore
        token=AgentStore(self.store).issue_token('hermes','alex','demo-margaret')
        other=PostgresStore(URL)
        try:
            def add(store):return AgentStore(store).add_word_draft(token,'same-request',text='Milo',kind='person')
            with ThreadPoolExecutor(2) as pool:
                a=pool.submit(add,self.store);b=pool.submit(add,other)
                first=a.result();second=b.result()
            self.assertEqual(first['word_id'],second['word_id'])
            self.assertEqual(sum(w.text=='Milo' for w in self.store.all_words('demo-margaret')),1)
        finally:other.close()

    def test_transaction_rolls_back_all_writes(self):
        before=len(self.store.audit_log())
        with self.assertRaises(RuntimeError):
            with self.store._db:
                self.store._db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',('sam','test','ids','now'))
                raise RuntimeError('abort')
        self.assertEqual(len(self.store.audit_log()),before)

    def test_real_api_and_plan_audio_persistence(self):
        import asyncio
        from unittest.mock import AsyncMock,patch
        from fastapi.testclient import TestClient
        from patient_listener.config import Settings
        from patient_listener.app.server import create_app
        from patient_listener.llm.reply import TemplateLlm
        from patient_listener.plan_generation import generate_plan
        token=self.store.issue_console_token('sam')
        cfg=Settings(database_url=URL,ai_enabled=False,voice_enabled=False,nebius_api_key='')
        with patch.dict(os.environ,{},clear=False):
            previous=os.environ.pop('PL_DB_PATH',None)
            try:
                with TestClient(create_app(cfg)) as client:
                    r=client.get('/api/console/words/margaret',headers={'Authorization':'Bearer '+token})
                    self.assertEqual(r.status_code,200)
                    r=client.post('/api/console/plans/margaret/generate',json={'render_audio':False},
                                  headers={'Authorization':'Bearer '+token})
                    self.assertEqual(r.status_code,200)
            finally:
                if previous is not None:os.environ['PL_DB_PATH']=previous
        result=asyncio.run(generate_plan(self.store,'demo-margaret',actor='sam',llm=TemplateLlm(),
            render=AsyncMock(return_value=b'\0\0'),tts_model='m',voice='v'))
        word=self.store._read_word(result['word_ids'][0])
        self.assertEqual(self.store.hint_audio('demo-margaret',word.id,1,word.hints.meaning,'m','v'),b'\0\0')

    def test_sqlite_transfer_requires_empty_target_and_preserves_wal_and_sequences(self):
        from patient_listener.store.transfer import import_sqlite,TABLES,quoted
        from patient_listener.store.sqlite_store import SqliteStore
        from patient_listener.schemas import Attempt
        from patient_listener.types import HintLevel,Outcome
        from patient_listener.tools.seed import seed_all
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'source.db');source=SqliteStore(path,ai_enabled=False);seed_all(source)
            source.log_attempt(Attempt(session_id='s',word_id='w-leo',hint_level=HintLevel.NONE,
                outcome=Outcome.FOUND,seconds_to_find=1,match_score=1,confirmed=True))
            with self.assertRaises(ValueError):import_sqlite(path,URL)
            with self.store._db:
                self.store._db.execute('TRUNCATE '+','.join(map(quoted,TABLES))+' RESTART IDENTITY')
            result=import_sqlite(path,URL)
            source.close()
            self.assertEqual(result['tables']['attempts'],1)
            self.assertFalse(result['credentials_copied'])
            self.assertEqual(len(self.store.words('demo-margaret')),4)
            self.store.log_attempt(Attempt(session_id='new',word_id='w-leo',hint_level=HintLevel.NONE,
                outcome=Outcome.FOUND,seconds_to_find=1,match_score=1,confirmed=True))
            self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2)

    def test_failed_statement_releases_write_transaction(self):
        from patient_listener.store.postgres_store import DatabaseOperationError, PostgresStore
        with self.assertRaises(DatabaseOperationError):
            self.store._db.execute('INSERT INTO audit (nonexistent_column) VALUES (?)', ('private',))
        other = PostgresStore(URL)
        try:
            other.set_ai_enabled(True)
            self.assertTrue(self.store.is_ai_enabled())
        finally:
            other.close()
