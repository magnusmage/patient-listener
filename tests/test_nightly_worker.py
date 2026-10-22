"""Nightly timing, durable admission and bounded spending; fake clocks and models only."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from patient_listener.app.deps import build_state
from patient_listener.app.nightly_worker import NightlyWorker
from patient_listener.app.server import create_app
from patient_listener.config import Settings
from patient_listener.store.sqlite_store import SqliteStore

NOW = datetime(2026,10,22,2,1,tzinfo=timezone.utc)


def config(**kwargs):
    base=Settings(ai_enabled=False,voice_enabled=False,nebius_api_key='',
        nightly_enabled=True,nightly_actor_id='sam',nightly_timezone='UTC',
        nightly_render_audio=False,nightly_max_words=1,nightly_use_ai=False)
    return replace(base,**kwargs)


class NightlyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cfg=config()
        self.state=build_state(settings=cfg)
        self.addCleanup(self.state.store.close)
        self.app=SimpleNamespace(state=SimpleNamespace(settings=cfg,pl=self.state,voice_runtime=None))
        store=self.state.store
        store.set_console_user('sam','Sam','therapist')
        store.link_console_user('sam','demo-margaret')

    def configure(self,**kwargs):
        cfg=replace(self.app.state.settings,**kwargs)
        self.app.state.settings=cfg; self.state.settings=cfg
        return NightlyWorker(self.app)

    async def test_disabled_and_before_schedule_make_no_plan(self):
        self.assertEqual(await self.configure(nightly_enabled=False).run_due(NOW),[])
        self.assertEqual(await self.configure(nightly_enabled=True).run_due(NOW.replace(hour=1)),[])
        self.assertEqual(self.state.store.nightly_runs('demo-margaret'),[])
        with self.assertRaises(ValueError):
            await self.configure().run_due(NOW.replace(tzinfo=None))

    async def test_runs_once_per_local_date_and_next_day_runs_again(self):
        worker=self.configure()
        self.assertEqual((await worker.run_due(NOW))[0]['status'],'succeeded')
        self.assertEqual(await worker.run_due(NOW),[])
        self.assertEqual(await NightlyWorker(self.app).run_due(NOW),[])
        result=await worker.run_due(NOW+timedelta(days=1))
        self.assertEqual(result[0]['status'],'succeeded')
        rows=self.state.store.nightly_runs('demo-margaret')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['reserved_calls'],0)

    async def test_timezone_defines_due_time_and_day(self):
        worker=self.configure(nightly_timezone='Asia/Karachi')
        # A fixed +05:00 zone tests midnight/date conversion without requiring the
        # host's optional IANA database. Real IANA names use zoneinfo on Linux.
        with patch('patient_listener.app.nightly_worker.schedule_timezone',
                   return_value=timezone(timedelta(hours=5))):
            result=await worker.run_due(datetime(2026,10,21,21,1,tzinfo=timezone.utc))
        self.assertEqual(result[0]['status'],'succeeded')
        self.assertEqual(self.state.store.nightly_runs('demo-margaret')[0]['local_day'],'2026-10-22')

    async def test_busy_person_and_gpu_are_not_consumed_as_daily_attempt(self):
        await self.state.sessions.claim('demo-margaret')
        worker=self.configure()
        self.assertEqual(await worker.run_due(NOW),[])
        self.assertEqual(self.state.store.nightly_runs('demo-margaret'),[])
        await self.state.sessions.release('demo-margaret')
        self.app.state.voice_runtime=SimpleNamespace()
        await self.state.sessions.claim('__gpu_voice__')
        worker=self.configure(nightly_render_audio=True)
        self.assertEqual(await worker.run_due(NOW),[])
        self.assertEqual(self.state.store.nightly_runs('demo-margaret'),[])
        self.assertFalse(await self.state.sessions.active('demo-margaret'))
        await self.state.sessions.release('__gpu_voice__')
        self.app.state.voice_runtime=None
        self.assertEqual((await self.configure(nightly_render_audio=False).run_due(NOW))[0]['status'],'succeeded')

    async def test_missing_permission_records_failure_without_calls(self):
        worker=self.configure(nightly_actor_id='unknown')
        with patch('patient_listener.llm.factory.build_llm') as factory:
            result=await worker.run_due(NOW)
            factory.assert_not_called()
        self.assertEqual(result[0]['reason'],'helper_not_authorized')
        self.assertEqual(await worker.run_due(NOW),[])
        self.assertEqual(self.state.store.nightly_runs('demo-margaret')[0]['reserved_calls'],0)

    async def test_no_approved_words_records_skip(self):
        self.state.store.link_console_user('sam','demo-daniyal')
        result=await self.configure(nightly_people=('daniyal',)).run_due(NOW)
        self.assertEqual(result[0]['status'],'skipped')
        self.assertEqual(result[0]['reason'],'no_approved_words')

    async def test_failed_generation_is_not_automatically_retried(self):
        worker=self.configure(nightly_render_audio=True)
        result=await worker.run_due(NOW)  # no loaded GPU
        self.assertEqual(result[0]['status'],'failed')
        self.assertEqual(await worker.run_due(NOW),[])
        self.assertEqual(self.state.store.nightly_runs('demo-margaret')[0]['summary'],
                         {'reason':'generation_http_503'})

    async def test_daily_model_budget_shared_across_people(self):
        store=self.state.store
        store.link_console_user('sam','demo-joseph')
        store.add_word_draft('w-cup','demo-joseph','cup','object',added_by='slt')
        store.approve_word('w-cup',by='slt')
        store.set_ai_enabled(True)
        worker=self.configure(ai_enabled=True,nebius_api_key='fake-key',nightly_use_ai=True,
                              nightly_max_model_calls=1,nightly_max_words=2,
                              nightly_people=('margaret','joseph'))
        fake=SimpleNamespace(plan=AsyncMock(return_value='A family pet.'))
        with patch('patient_listener.llm.factory.build_llm',return_value=fake), patch(
                'importlib.util.find_spec',return_value=object()):
            result=await worker.run_due(NOW)
        self.assertEqual(fake.plan.await_count,1)
        self.assertEqual(sum(r['model_attempts'] for r in result),1)
        self.assertEqual(sum(self.state.store.nightly_runs(p)[0]['reserved_calls']
                             for p in ('demo-margaret','demo-joseph')),1)
        self.assertEqual(result[1]['model_hints'],0)

    async def test_saved_switch_off_uses_templates_even_if_nightly_ai_requested(self):
        worker=self.configure(nightly_use_ai=True)
        result=await worker.run_due(NOW)
        self.assertEqual(result[0]['model_attempts'],0)
        self.assertEqual(self.state.store.nightly_runs('demo-margaret')[0]['reserved_calls'],0)

    async def test_interrupted_paid_attempt_stays_running_and_is_not_repeated(self):
        self.state.store.set_ai_enabled(True)
        worker=self.configure(ai_enabled=True,nebius_api_key='fake-key',nightly_use_ai=True)
        fake=SimpleNamespace(plan=AsyncMock(side_effect=asyncio.CancelledError))
        with patch('patient_listener.llm.factory.build_llm',return_value=fake), patch(
                'importlib.util.find_spec',return_value=object()):
            with self.assertRaises(asyncio.CancelledError):
                await worker.run_due(NOW)
            self.assertEqual(await NightlyWorker(self.app).run_due(NOW),[])
        row=self.state.store.nightly_runs('demo-margaret')[0]
        self.assertEqual(row['status'],'running')
        self.assertEqual(row['reserved_calls'],1)
        self.assertFalse(await self.state.sessions.active('demo-margaret'))
        self.assertEqual(fake.plan.await_count,1)

    async def test_zero_or_exhausted_budget_uses_templates_without_model_configuration(self):
        self.state.store.set_ai_enabled(True)
        worker=self.configure(nightly_use_ai=True,nightly_max_model_calls=0,nebius_api_key='')
        result=await worker.run_due(NOW)
        self.assertEqual(result[0]['status'],'succeeded')
        self.assertEqual(result[0]['model_attempts'],0)
        day=(NOW+timedelta(days=1)).date().isoformat()
        self.state.store.claim_nightly(day,'another-person','sam',1,1)
        result=await self.configure(nightly_max_model_calls=1).run_due(NOW+timedelta(days=1))
        self.assertEqual(result[0]['status'],'succeeded')
        self.assertEqual(result[0]['model_attempts'],0)

    async def test_aliases_for_same_person_do_not_repeat(self):
        result=await self.configure(nightly_people=('margaret','demo-margaret')).run_due(NOW)
        self.assertEqual(len(result),1)


class LedgerTests(unittest.TestCase):
    def test_reservations_survive_database_restart_and_share_global_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'pl.db')
            store=SqliteStore(path)
            self.assertEqual(store.claim_nightly('2026-10-22','p1','sam',2,3),2)
            store.close()
            store=SqliteStore(path)
            try:
                self.assertIsNone(store.claim_nightly('2026-10-22','p1','sam',2,3))
                self.assertEqual(store.claim_nightly('2026-10-22','p2','sam',2,3),1)
                self.assertEqual(store.claim_nightly('2026-10-22','p3','sam',2,3),0)
            finally: store.close()


class NightlyLifecycleTests(unittest.TestCase):
    def test_scheduler_disabled_by_default(self):
        with TestClient(create_app(Settings(ai_enabled=False,voice_enabled=False))) as client:
            self.assertIsNone(client.app.state.nightly_task)

    def test_scheduler_requires_persistent_database(self):
        with patch.dict('os.environ',{'PL_DB_PATH':':memory:'}):
            with self.assertRaisesRegex(ValueError,'persistent'):
                with TestClient(create_app(config())): pass

    def test_worker_starts_and_is_cancelled_before_store_closes(self):
        stopped=[]
        async def run(worker):
            try: await asyncio.Event().wait()
            finally:
                worker.app.state.pl.store.is_ai_enabled()
                stopped.append(True)
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ',
                {'PL_DB_PATH':str(Path(temp)/'pl.db')}), patch.object(NightlyWorker,'run',run):
            with TestClient(create_app(config())) as client:
                task=client.app.state.nightly_task
                self.assertFalse(task.done())
            self.assertTrue(task.done())
            self.assertEqual(stopped,[True])

    def test_nightly_status_is_authenticated_and_person_scoped(self):
        with TestClient(create_app(Settings(ai_enabled=False,voice_enabled=False))) as client:
            store=client.app.state.pl.store
            store.set_console_user('sam','Sam','therapist');store.link_console_user('sam','demo-margaret')
            headers={'Authorization':'Bearer '+store.issue_console_token('sam')}
            self.assertEqual(client.get('/api/console/nightly/margaret').status_code,401)
            self.assertEqual(client.get('/api/console/nightly/joseph',headers=headers).status_code,404)
            response=client.get('/api/console/nightly/margaret',headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(response.json()['runs'],[])

    def test_bad_schedule_configuration_is_rejected(self):
        for cfg in (config(nightly_actor_id=''),config(nightly_people=()),
                    config(nightly_time='25:00'),config(nightly_time='2:00'),
                    config(nightly_max_words=0),config(nightly_max_model_calls=-1)):
            with self.assertRaises(ValueError): cfg.assert_safe_startup()
