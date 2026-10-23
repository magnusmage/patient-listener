"""FR-11/61: saved profiles, safe helper edits and patient-only extensions."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from patient_listener.app.session import AppSession
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.types import HintLevel, Need

try:
    from fastapi.testclient import TestClient
    from patient_listener.app.server import create_app
    from patient_listener.config import Settings
    HAVE_API = True
except ImportError:
    HAVE_API = False


def config():
    return Settings(ai_enabled=False, nebius_api_key='', voice_enabled=False, console_demo_enabled=False)


@unittest.skipUnless(HAVE_API, 'needs api extra')
class ProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(config()))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.store = self.client.app.state.pl.store
        self.slt = self.identity('sam','therapist','demo-margaret')
        self.carer = self.identity('alex','carer','demo-margaret')

    def identity(self, name, role, pid=None):
        self.store.set_console_user(name,name,role)
        if pid: self.store.link_console_user(name,pid)
        return {'Authorization':'Bearer '+self.store.issue_console_token(name)}

    def update(self, body, headers=None, person='margaret'):
        return self.client.patch('/api/console/settings/'+person,
                                 json=body,headers=headers if headers is not None else self.slt)

    def test_save_all_settings_and_new_session_uses_them(self):
        response = self.update({'needs':['finding_words','being_clear'], 'backchannel_s':6,
            'offer_hint_s':9, 'max_wait_s':30, 'max_session_min':25,
            'hint_order':['sound','meaning','word']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        body=response.json()
        self.assertEqual(body['hintOrder'],'sound-first')
        self.assertEqual(body['hintWait'],9)
        self.assertEqual(body['values']['max_wait_s'],30)
        self.assertTrue(body['canEdit'])
        self.assertEqual(self.store.audit_log()[-1]['actor'],'sam')
        self.assertEqual(self.store.audit_log()[-1]['detail'],'demo-margaret')
        async def send(event): pass
        s=AppSession(self.store,'demo-margaret',send)
        self.assertEqual(s.cfg.needs,frozenset({Need.FINDING_WORDS,Need.BEING_CLEAR}))
        self.assertEqual(s.cfg.hint_order,(HintLevel.SOUND,HintLevel.MEANING,HintLevel.WORD))
        self.assertEqual((s.cfg.offer_hint_s,s.cfg.max_wait_s,s.cfg.max_session_min),(9,30,25))
        self.assertEqual(self.store.load_plan('demo-margaret').pause,s.cfg)

    def test_carer_with_therapist_has_read_only_profile(self):
        response=self.client.get('/api/console/settings/margaret',headers=self.carer)
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['canEdit'])
        before=self.store.person_pause('demo-margaret')
        self.assertEqual(self.update({'max_session_min':30},headers=self.carer).status_code,403)
        self.assertEqual(self.store.person_pause('demo-margaret'),before)

    def test_carer_without_therapist_can_save(self):
        self.store._db.execute("DELETE FROM console_links WHERE user_id='sam'")
        self.store._db.commit()
        response=self.update({'offer_hint_s':9},headers=self.carer)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['canEdit'])

    def test_unauthenticated_unlinked_and_agent_edits_are_denied(self):
        self.assertEqual(self.update({'max_session_min':30},headers={}).status_code,401)
        other=self.identity('other','therapist','demo-joseph')
        self.assertEqual(self.update({'max_session_min':30},headers=other).status_code,404)
        agent=self.identity('agent','agent','demo-margaret')
        self.assertEqual(self.update({'max_session_min':30},headers=agent).status_code,403)
        with self.assertRaises(PermissionError):
            self.store.console_update_profile('demo-margaret',{'max_session_min':30},actor='other')

    def test_invalid_changes_are_atomic_and_cannot_edit_internal_rules(self):
        before=self.store.person_pause('demo-margaret')
        cases=[{}, {'needs':[]}, {'needs':['finding_words','finding_words']}, {'needs':None},
            {'needs':['diagnosis']}, {'needs':['listening']}, {'max_turns':100},
            {'needs_complete_text':False}, {'person_id':'demo-joseph'}, {'backchannel_s':True},
            {'backchannel_s':1}, {'backchannel_s':16}, {'offer_hint_s':3}, {'offer_hint_s':16},
            {'max_wait_s':7}, {'max_wait_s':121}, {'max_session_min':2}, {'max_session_min':121},
            {'max_session_min':3.5}, {'hint_order':None}, {'max_wait_s':'30'},
            {'hint_order':['word','sound','meaning']}, {'hint_order':['sound','sound','word']}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.update(changes).status_code,422)
                self.assertEqual(self.store.person_pause('demo-margaret'),before)

    def test_words_out_disables_incompatible_old_overrides_and_cannot_be_reenabled(self):
        self.assertEqual(self.update({'backchannel_s':6,'offer_hint_s':9}).status_code,200)
        response=self.update({'needs':['finding_words','words_out']})
        self.assertEqual(response.status_code,200)
        cfg=self.store.person_pause('demo-margaret')
        self.assertIsNone(cfg.backchannel_s)
        self.assertIsNone(cfg.offer_hint_s)
        self.assertTrue(cfg.needs_complete_text)
        self.assertEqual(cfg.max_wait_s,20)
        for changes in ({'backchannel_s':4},{'offer_hint_s':7}):
            self.assertEqual(self.update(changes).status_code,422)
        self.assertEqual(self.store.person_pause('demo-margaret'),cfg)

    def test_saved_multi_need_profile_retains_saving_energy_rules(self):
        self.update({'needs':['being_clear','saving_energy'], 'max_session_min':None})
        cfg=self.store.person_pause('demo-margaret')
        self.assertEqual(cfg.max_turns,15)
        self.assertEqual(cfg.rest_every_turns,5)
        self.assertIn('one_more',cfg.banned_phrases)
        self.assertIsNone(cfg.max_session_min)

    def test_explicit_patient_never_preference_survives_need_changes(self):
        self.store.patient_extend_profile('demo-margaret',{'backchannel_s':None})
        self.update({'needs':['words_out']})
        self.update({'needs':['finding_words']})
        self.assertIsNone(self.store.person_pause('demo-margaret').backchannel_s)

    def test_authenticated_websocket_extensions_persist_for_token_person(self):
        device='a'*48
        token=self.client.get('/api/session',headers={'X-PL-Device':device}).json()['token']
        with self.client.websocket_connect('/ws?token='+token+'&device='+device) as ws:
            ws.send_json({'type':'start'})
            for _ in range(6):
                if ws.receive_json()['type']=='prompt': break
            ws.send_json({'type':'extend_settings','max_wait_s':60})
            for _ in range(6):
                if ws.receive_json()['type']=='settingsSaved': break
            else: self.fail('settings were not acknowledged')
            self.assertEqual(self.store.person_pause('demo-margaret').max_wait_s,60)
            self.assertEqual(self.store.person_pause('demo-joseph').max_wait_s,12)

    def test_delete_removes_profile_overrides(self):
        self.update({'max_wait_s':60,'needs':['being_clear']})
        self.store.delete_all('demo-margaret')
        self.assertFalse(self.store.person_exists('demo-margaret'))
        self.assertIsNone(self.store._db.execute('SELECT data FROM person_settings WHERE person_id=?', ('demo-margaret',)).fetchone())
        with self.assertRaises(ValueError):
            self.store.add_person('demo-margaret','New',frozenset({Need.FINDING_WORDS}))
        self.store.add_person('replacement-person','New',frozenset({Need.FINDING_WORDS}))
        self.assertEqual(self.store.person_pause('replacement-person').max_wait_s,20)
        self.assertEqual(self.store.person_needs('replacement-person'),frozenset({Need.FINDING_WORDS}))

    def test_restart_reseeding_does_not_replace_saved_needs_or_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ',{'PL_DB_PATH':str(Path(directory)/'profile.db')}):
                with TestClient(create_app(config())) as client:
                    store=client.app.state.pl.store
                    store.set_console_user('slt','SLT','therapist')
                    store.link_console_user('slt','demo-margaret')
                    headers={'Authorization':'Bearer '+store.issue_console_token('slt')}
                    self.assertEqual(client.patch('/api/console/settings/margaret',headers=headers,
                        json={'needs':['being_clear'],'max_wait_s':60,'max_session_min':None}).status_code,200)
                with TestClient(create_app(config())) as client:
                    body=client.get('/api/console/settings/margaret',headers=headers).json()
                    self.assertEqual(body['needKeys'],['being_clear'])
                    self.assertEqual(body['maxWait'],60)
                    self.assertIsNone(body['sessionMin'])


class PatientSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=SqliteStore(check_same_thread=False,ai_enabled=False)
        self.pid=seed_all(self.store)['margaret']
        self.events=[]
        async def send(event): self.events.append(event)
        self.s=AppSession(self.store,self.pid,send)
        await self.s.start()

    async def asyncTearDown(self):
        tasks=[t for t in (self.s._ticker,self.s._advance,self.s._cap) if t]
        self.s.close()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.store.close()

    async def test_patient_can_lengthen_and_disable_without_pin_for_this_person_only(self):
        await self.s.handle({'type':'extend_settings','backchannel_s':10,'offer_hint_s':12,
                             'max_wait_s':60,'max_session_min':30})
        cfg=self.store.person_pause(self.pid)
        self.assertEqual((cfg.backchannel_s,cfg.offer_hint_s,cfg.max_wait_s,cfg.max_session_min),(10,12,60,30))
        self.assertEqual(self.s.cfg,cfg)
        self.assertEqual(self.s.engine.controller.cfg,cfg)
        self.assertEqual(self.store.person_pause('demo-joseph').max_wait_s,12)
        await self.s.handle({'type':'extend_settings','backchannel_s':None,'offer_hint_s':None,
                             'max_wait_s':None,'max_session_min':None})
        self.assertIsNone(self.s._cap)
        self.assertIsNone(self.store.person_pause(self.pid).max_wait_s)
        self.assertTrue(any(e['type']=='settingsSaved' for e in self.events))

    async def test_shortening_protected_fields_and_foreign_person_are_denied(self):
        before=self.store.person_pause(self.pid)
        cases=[{'max_wait_s':8},{'max_session_min':10},{'offer_hint_s':4},
               {'needs':['being_clear']},{'hint_order':['sound','meaning','word']},
               {'person_id':'demo-joseph','max_wait_s':60},{'max_wait_s':True},{}]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                await self.s.handle({'type':'extend_settings',**changes})
            self.assertEqual(self.store.person_pause(self.pid),before)

    async def test_disabled_wait_cannot_be_reenabled_by_patient(self):
        await self.s.handle({'type':'extend_settings','backchannel_s':None})
        with self.assertRaises(ValueError):
            await self.s.handle({'type':'extend_settings','backchannel_s':15})
        self.assertIsNone(self.s.cfg.backchannel_s)

    async def test_console_changes_apply_next_session_without_switching_active_needs(self):
        self.store.set_console_user('slt','SLT','therapist')
        self.store.link_console_user('slt',self.pid)
        self.store.console_update_profile(self.pid,{'needs':['being_clear']},actor='slt')
        self.assertEqual(self.s.cfg.needs,frozenset({Need.FINDING_WORDS}))
        await self.s.handle({'type':'extend_settings','max_wait_s':60})
        self.assertEqual(self.s.cfg.needs,frozenset({Need.FINDING_WORDS}))
        self.assertEqual(self.store.person_needs(self.pid),frozenset({Need.BEING_CLEAR}))

    async def test_extension_cannot_shorten_latest_stored_settings(self):
        self.store.patient_extend_profile(self.pid,{'max_wait_s':80})
        with self.assertRaises(ValueError):
            await self.s.handle({'type':'extend_settings','max_wait_s':60})
        self.assertEqual(self.store.person_pause(self.pid).max_wait_s,80)
