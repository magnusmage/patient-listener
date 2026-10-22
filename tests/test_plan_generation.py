"""On-demand plan contract, publication and real playback path with fake models only."""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.app.session import AppSession
from patient_listener.config import Settings
from patient_listener.llm.reply import TemplateLlm
from patient_listener.plan_generation import generate_plan, PlanConflict, select_words
from patient_listener.schemas import Plan, PlanItem
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = SqliteStore(ai_enabled=True)
        self.addCleanup(self.store.close)
        seed_all(self.store)
        self.store.set_console_user('sam','Sam','therapist')
        self.store.link_console_user('sam','demo-margaret')
        self.llm = SimpleNamespace(plan=AsyncMock(return_value='A family pet.'))

    async def generate(self, **kwargs):
        return await generate_plan(self.store, 'demo-margaret', actor='sam', llm=self.llm, **kwargs)

    async def test_default_is_one_word_no_model_calls_and_session_uses_saved_plan(self):
        result = await self.generate()
        self.assertEqual(result['plan_items'], 1)
        self.assertEqual(result['model_attempts'], 0)
        self.llm.plan.assert_not_awaited()
        session = AppSession(self.store,'demo-margaret',AsyncMock())
        self.assertEqual([w.id for w in session.words], result['word_ids'])
        self.assertIsNotNone(session.words[0].hints)
        self.assertEqual(self.store.audit_log()[-1]['actor'], 'sam')

    async def test_model_hints_and_all_three_clips_are_saved_for_exact_text(self):
        result = await self.generate(use_ai=True, render=AsyncMock(return_value=b'\0\0'),
                                     tts_model='model', voice='voice')
        self.assertEqual(result['model_attempts'], 1)
        self.assertEqual(result['model_hints'], 1)
        self.assertEqual(result['rendered_clips'], 3)
        word = next(w for w in self.store.words('demo-margaret') if w.id == result['word_ids'][0])
        for level, text in enumerate((word.hints.meaning,word.hints.sound,word.hints.word),1):
            self.assertEqual(self.store.hint_audio('demo-margaret',word.id,level,text,'model','voice'),b'\0\0')
            self.assertIsNone(self.store.hint_audio('demo-margaret',word.id,level,text+' stale','model','voice'))
            self.assertIsNone(self.store.hint_audio('demo-joseph',word.id,level,text,'model','voice'))
            self.assertIsNone(self.store.hint_audio('demo-margaret',word.id,level,text,'other','voice'))

    async def test_error_or_invalid_model_meaning_uses_templates_without_retry(self):
        for response in ('Biscuit the puppy.', [], ''):
            self.llm.plan.return_value = response
            self.llm.plan.reset_mock()
            result = await self.generate(use_ai=True)
            self.assertEqual(result['model_hints'], 0)
            self.assertEqual(self.llm.plan.await_count, 1)
        self.llm.plan.side_effect = RuntimeError('private error')
        self.assertEqual((await self.generate(use_ai=True))['template_hints'],1)

    async def test_ai_disabled_never_calls_super(self):
        self.store.set_ai_enabled(False)
        result = await self.generate(use_ai=True)
        self.assertEqual(result['model_attempts'], 0)
        self.llm.plan.assert_not_awaited()

    async def test_renderer_failure_keeps_previous_plan_and_hints(self):
        first = await self.generate()
        before = self.store.load_plan('demo-margaret')
        hints = {w.id:w.hints for w in self.store.words('demo-margaret')}
        with self.assertRaises(RuntimeError):
            await self.generate(max_words=2,render=AsyncMock(side_effect=[b'\0\0',RuntimeError('tts')]))
        self.assertEqual(self.store.load_plan('demo-margaret'),before)
        self.assertEqual({w.id:w.hints for w in self.store.words('demo-margaret')},hints)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM hint_audio').fetchone()[0],0)

    async def test_switch_off_during_render_does_not_publish_model_content(self):
        async def render(text):
            self.store.set_ai_enabled(False)
            return b'\0\0'
        with self.assertRaises(PlanConflict):
            await self.generate(use_ai=True,render=render)
        self.assertIsNone(self.store._db.execute('SELECT * FROM plans').fetchone())

    async def test_changed_word_or_revoked_link_cannot_publish(self):
        async def render(text):
            self.store._db.execute("UPDATE words SET meaning_cue='changed' WHERE id='w-biscuit'")
            self.store._db.commit()
            return b'\0\0'
        with self.assertRaises(PlanConflict):
            await self.generate(render=render)
        self.assertIsNone(self.store._db.execute('SELECT * FROM plans').fetchone())
        async def revoke(text):
            self.store._db.execute("DELETE FROM console_links WHERE user_id='sam'")
            self.store._db.commit()
            return b'\0\0'
        with self.assertRaises(PermissionError):
            await self.generate(render=revoke)

    async def test_drafts_and_obsolete_cards_are_not_selected(self):
        self.store.add_word_draft('draft','demo-margaret','draft','object',added_by='carer')
        from patient_listener.schedule.fsrs import Card
        self.store.set_card('demo-margaret','removed',Card.new().to_json())
        words, _ = select_words(self.store,'demo-margaret',1)
        self.assertEqual(len(words),1)
        self.assertNotIn(words[0].id, ('draft','removed'))

    async def test_plan_order_and_prompts_are_used(self):
        plan = Plan('demo-margaret','review',(PlanItem('w-whitby','due','Where is this?'),
                    PlanItem('w-leo','due','Who is this?')),self.store.person_pause('demo-margaret'))
        self.store.save_plan(plan)
        send = AsyncMock()
        session = AppSession(self.store,'demo-margaret',send)
        self.assertEqual([w.id for w in session.words],['w-whitby','w-leo'])
        await session.next_prompt()
        self.assertTrue(any(c.args[0].get('text') == 'Where is this?' for c in send.await_args_list))
        session.close()

    async def test_published_plan_and_audio_survive_restart_and_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SqliteStore(str(Path(temp)/'pl.db'))
            seed_all(store)
            store.set_console_user('sam','Sam','therapist'); store.link_console_user('sam','demo-margaret')
            await generate_plan(store,'demo-margaret',actor='sam',llm=TemplateLlm(),
                                render=AsyncMock(return_value=b'\0\0'),tts_model='m',voice='v')
            word = store.load_plan('demo-margaret').items[0].word_id
            text = next(w.hints.meaning for w in store.words('demo-margaret') if w.id == word)
            store.close()
            store = SqliteStore(str(Path(temp)/'pl.db'))
            try:
                seed_all(store)
                self.assertEqual(len(store.load_plan('demo-margaret').items),1)
                self.assertIsNotNone(next(w.hints for w in store.words('demo-margaret') if w.id == word))
                self.assertEqual(store.hint_audio('demo-margaret',word,1,text,'m','v'),b'\0\0')
                store.delete_all('demo-margaret')
                self.assertEqual(store._db.execute('SELECT COUNT(*) FROM hint_audio').fetchone()[0],0)
            finally: store.close()


    async def test_database_failure_rolls_back_hint_and_plan_publication(self):
        await self.generate()
        before = self.store.load_plan('demo-margaret')
        hints = {w.id: w.hints for w in self.store.words('demo-margaret')}
        self.store._db.execute("CREATE TRIGGER reject_clip BEFORE INSERT ON hint_audio BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(Exception):
            await self.generate(max_words=2, use_ai=True, render=AsyncMock(return_value=b'\0\0'))
        self.assertEqual(self.store.load_plan('demo-margaret'), before)
        self.assertEqual({w.id:w.hints for w in self.store.words('demo-margaret')}, hints)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM hint_audio').fetchone()[0], 0)

    async def test_unsafe_user_cue_gets_validated_neutral_template(self):
        self.store._db.execute("UPDATE words SET meaning_cue='bison in a garden' WHERE id='w-biscuit'")
        self.store._db.commit()
        await self.generate()
        word = next(w for w in self.store.words('demo-margaret') if w.id == 'w-biscuit')
        from patient_listener.llm.validate import check_meaning_hint
        self.assertTrue(check_meaning_hint(word.hints.meaning, word.text).ok)
        self.assertNotIn('bison', word.hints.meaning)


class PlanApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(Settings(ai_enabled=False,voice_enabled=False,
            nebius_api_key='',console_demo_enabled=False)))
        self.client.__enter__(); self.addCleanup(self.client.__exit__,None,None,None)
        self.store = self.client.app.state.pl.store
        self.slt = self.identity('sam','therapist','demo-margaret')
        self.carer = self.identity('alex','carer','demo-margaret')

    def identity(self,name,role,pid):
        self.store.set_console_user(name,name,role); self.store.link_console_user(name,pid)
        return {'Authorization':'Bearer '+self.store.issue_console_token(name)}

    def generate(self,body=None,headers=None):
        return self.client.post('/api/console/plans/margaret/generate',
            json=body if body is not None else {'render_audio':False},
            headers=self.slt if headers is None else headers)

    def test_text_plan_and_access_controls(self):
        response=self.generate()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['model_attempts'],0)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(self.generate(headers={}).status_code,401)
        self.assertEqual(self.generate(headers=self.carer).status_code,403)
        other=self.identity('other','therapist','demo-joseph')
        self.assertEqual(self.generate(headers=other).status_code,404)
        agent=self.identity('agent','agent','demo-margaret')
        self.assertEqual(self.generate(headers=agent).status_code,403)
        self.store._db.execute("DELETE FROM console_links WHERE user_id='sam'");self.store._db.commit()
        self.assertEqual(self.generate(headers=self.carer).status_code,200)

    def test_invalid_options_and_unavailable_voice_or_ai(self):
        for body in ({'max_words':0},{'max_words':11},{'max_words':True},
                     {'max_words':1.5},{'use_ai':'yes'},{'actor':'sam'}):
            self.assertEqual(self.generate(body).status_code,422)
        self.assertEqual(self.generate({}).status_code,503)
        self.assertEqual(self.generate({'render_audio':False,'use_ai':True}).status_code,409)

    def test_gpu_busy_releases_person_and_render_failure_keeps_plan(self):
        runtime=SimpleNamespace(gpu_lock=threading.Lock(),close=lambda:None)
        self.client.app.state.voice_runtime=runtime
        # Use the test portal to claim the same registry as the API event loop.
        registry=self.client.app.state.pl.sessions
        with patch.object(registry,'claim',new=AsyncMock(side_effect=[True,False])):
            self.assertEqual(self.generate({}).status_code,409)
        with patch('patient_listener.app.nemo_stream.synthesize',side_effect=RuntimeError('private')):
            self.assertEqual(self.generate({}).status_code,503)
        self.assertIsNone(self.store._db.execute('SELECT * FROM plans').fetchone())
        self.assertEqual(self.generate().status_code,200)
        self.client.app.state.voice_runtime=None

    def test_audio_generation_reuses_loaded_runtime(self):
        runtime=SimpleNamespace(gpu_lock=threading.Lock(),close=lambda:None)
        self.client.app.state.voice_runtime=runtime
        with patch('patient_listener.app.nemo_stream.synthesize',return_value=b'\0\0') as synth:
            response=self.generate({})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['rendered_clips'],3)
        self.assertEqual(synth.call_count,3)
        self.client.app.state.voice_runtime=None
