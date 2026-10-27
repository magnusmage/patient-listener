"""Cue edits and patient-owned settings: permissions, derived data and live timers."""
import asyncio
import unittest
from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.app.session import AppSession
from patient_listener.config import Settings
from patient_listener.schemas import HintLines
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all

PID = 'demo-margaret'
DEVICE = 'a' * 48


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(Settings(ai_enabled=False, nebius_api_key='',
            voice_enabled=False, patient_enrollment_required=True, console_demo_enabled=True)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.client.app.state.pl.store
        self.sam = self.helper('sam', 'therapist', PID)
        self.alex = self.helper('alex', 'carer', PID)
        self.device = {'X-PL-Device': DEVICE}

    def helper(self, name, role, pid):
        self.store.set_console_user(name, name, role)
        self.store.link_console_user(name, pid)
        return {'Authorization': 'Bearer ' + self.store.issue_console_token(name)}

    def enroll(self):
        code = self.client.post('/api/console/patients/margaret/device-links',
                                headers=self.sam).json()['setup_code']
        self.assertEqual(self.client.post('/api/patient/enroll',headers=self.device,
                         json={'setup_code': code}).status_code, 200)

    def edit(self, payload=None, headers=None, person='margaret', word='w-biscuit'):
        return self.client.patch('/api/console/words/'+person+'/'+word,
            headers=self.sam if headers is None else headers,
            json={'meaning_cue':'a small family pet'} if payload is None else payload)

    def test_edit_preserves_word_approval_and_clears_only_affected_derived_data(self):
        original = self.store._read_word('w-biscuit')
        hints = HintLines('old cue','It starts with B.',"It is Biscuit.")
        self.store.set_word_hints('w-biscuit', hints)
        for wid in ('w-biscuit','w-leo'):
            self.store._db.execute('INSERT INTO hint_audio VALUES (?,?,?,?,?,?,?,?)',
                                  (PID,wid,1,'old','model','voice',b'xx','profile'))
        self.store._db.commit()
        result = self.edit()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'],'no-store')
        self.assertEqual(result.json()['word']['cue'],'a small family pet')
        word = self.store._read_word('w-biscuit')
        for field in ('text','kind','status','approved_by','added_by','first_sound'):
            self.assertEqual(getattr(word,field),getattr(original,field))
        self.assertIsNone(word.hints)
        rows=self.store._db.execute('SELECT word_id FROM hint_audio').fetchall()
        self.assertEqual([r['word_id'] for r in rows],['w-leo'])
        audit=self.store.audit_log()[-1]
        self.assertEqual(audit['action'],'edit_meaning_cue')
        self.assertNotIn('small family',audit['detail'])

    def test_cue_permissions_and_word_scope(self):
        self.assertEqual(self.edit(headers={}).status_code,401)
        self.assertEqual(self.edit(headers=self.alex).status_code,403)
        for role in ('patient','agent'):
            self.assertEqual(self.edit(headers=self.helper(role,role,PID)).status_code,403)
        other=self.helper('other','therapist','demo-joseph')
        self.assertEqual(self.edit(headers=other).status_code,404)
        self.assertEqual(self.edit(person='joseph').status_code,404)
        self.store.link_console_user('sam','demo-joseph')
        self.assertEqual(self.edit(person='joseph').status_code,404)
        self.assertEqual(self.edit(word='missing').status_code,404)

    def test_unopposed_carer_can_edit_and_empty_cue_can_clear(self):
        self.store.set_console_user('sam','Sam','carer')
        self.assertEqual(self.edit(headers=self.alex,payload={'meaning_cue':''}).status_code,200)
        self.assertEqual(self.store._read_word('w-biscuit').meaning_cue,'')

    def test_invalid_cue_patch_does_not_write(self):
        before=self.store._read_word('w-biscuit')
        for payload in ({},{'meaning_cue':None},{'meaning_cue':3},{'meaning_cue':'x'*91},
                        {'meaning_cue':'a\nb'},{'meaning_cue':'new','status':'approved'},
                        {'text':'replacement'}):
            self.assertEqual(self.edit(payload=payload).status_code,422)
        self.assertEqual(self.store._read_word('w-biscuit'),before)

    def test_noop_edit_keeps_prepared_hints(self):
        hints=HintLines('a cue','B','Biscuit')
        self.store.set_word_hints('w-biscuit',hints)
        cue=self.store._read_word('w-biscuit').meaning_cue
        self.assertEqual(self.edit(payload={'meaning_cue':cue}).status_code,200)
        self.assertEqual(self.store._read_word('w-biscuit').hints,hints)

    def test_busy_patient_blocks_edit_and_http_settings(self):
        self.enroll()
        registry=self.client.app.state.pl.sessions
        self.client.portal.call(registry.claim,PID)
        self.addCleanup(self.client.portal.call,registry.release,PID)
        self.assertEqual(self.edit().status_code,409)
        result=self.client.patch('/api/session/settings',headers=self.device,json={'max_wait_s':60})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.store.person_pause(PID).max_wait_s,20)

    def test_settings_require_enrolled_matching_device_and_patient(self):
        self.assertEqual(self.client.get('/api/session/settings',headers=self.sam).status_code,401)
        self.enroll()
        self.assertEqual(self.client.get('/api/session/settings',headers={'X-PL-Device':'b'*48}).status_code,401)
        self.assertEqual(self.client.get('/api/session/settings?person=joseph',headers=self.device).status_code,401)
        result=self.client.get('/api/session/settings?person=demo-margaret',headers=self.device)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['settings']['max_wait_s'],20)
        self.assertEqual(result.headers['cache-control'],'no-store')

    def test_settings_extend_disable_and_do_not_touch_other_patient(self):
        self.enroll()
        for changes in ({'max_wait_s':60,'max_session_min':30},
                        {'backchannel_s':None,'offer_hint_s':None,'max_wait_s':None,'max_session_min':None}):
            result=self.client.patch('/api/session/settings',headers=self.device,json=changes)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['applies_to'],'next_session')
        self.assertIsNone(self.store.person_pause(PID).max_wait_s)
        self.assertEqual(self.store.person_pause('demo-joseph').max_wait_s,12)
        self.assertEqual(self.client.patch('/api/session/settings',headers=self.device,
                         json={'max_wait_s':120}).status_code,403)

    def test_shortening_and_unsupported_fields_are_rejected(self):
        self.enroll()
        before=self.store.person_pause(PID)
        for changes,code in [({'max_wait_s':8},403),({'backchannel_s':2},403),
             ({'max_session_min':10},403),({'needs':['being_clear']},422),
             ({'hint_order':['sound','meaning','word']},422),({},422),
             ({'max_wait_s':True},422),({'max_wait_s':121},422),
             ({'max_session_min':30.5},422),({'person':'joseph','max_wait_s':60},422)]:
            result=self.client.patch('/api/session/settings',headers=self.device,json=changes)
            self.assertEqual(result.status_code,code,(changes,result.text))
            self.assertEqual(self.store.person_pause(PID),before)

    def test_live_websocket_returns_settings_and_http_refuses_stale_controller_update(self):
        self.enroll()
        token=self.client.get('/api/session',headers=self.device).json()['token']
        with self.client.websocket_connect('/ws?token='+token+'&device='+DEVICE) as ws:
            ws.send_json({'type':'get_settings'})
            self.assertEqual(ws.receive_json()['settings']['max_wait_s'],20)
            self.assertEqual(self.client.patch('/api/session/settings',headers=self.device,
                json={'max_wait_s':60}).status_code,409)
            self.assertEqual(self.edit().status_code,409)
            ws.send_json({'type':'extend_settings','max_wait_s':60})
            ack=ws.receive_json()
            self.assertEqual(ack['type'],'settingsSaved')
            self.assertEqual(ack['settings']['max_wait_s'],60)
        self.assertEqual(self.store.person_pause(PID).max_wait_s,60)

    def test_revocation_blocks_settings(self):
        self.enroll()
        device=self.client.get('/api/console/patients/margaret/devices',headers=self.sam).json()['devices'][0]
        self.client.delete('/api/console/patients/margaret/devices/'+device['authorization_id'],headers=self.sam)
        self.assertEqual(self.client.get('/api/session/settings',headers=self.device).status_code,401)


class LiveSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=SqliteStore(check_same_thread=False,ai_enabled=False)
        self.pid=seed_all(self.store)['margaret']
        self.events=[]
        async def send(event):self.events.append(event)
        self.session=AppSession(self.store,self.pid,send)
        await self.session.start()

    async def asyncTearDown(self):
        tasks=[t for t in (self.session._ticker,self.session._advance,self.session._cap) if t]
        self.session.close()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.store.close()

    async def test_read_and_ack_return_authoritative_values(self):
        await self.session.handle({'type':'get_settings'})
        self.assertEqual(self.events[-1]['settings']['max_wait_s'],20)
        await self.session.handle({'type':'extend_settings','max_wait_s':60})
        self.assertEqual(self.events[-1]['type'],'settingsSaved')
        self.assertEqual(self.events[-1]['settings']['max_wait_s'],60)
        self.assertEqual(self.session.engine.controller.cfg.max_wait_s,60)
        with self.assertRaises(ValueError):
            await self.session.handle({'type':'get_settings','person':'other'})

    async def test_live_change_reschedules_sleep_without_resetting_silence(self):
        session=self.session
        session.now = lambda: 5.0
        session.engine.controller.on_silence(0.0)
        since=session.engine.controller.silence_started
        delays=[]
        sleeping=asyncio.Event()
        async def fake_sleep(delay):
            delays.append(delay)
            sleeping.set()
            await asyncio.Event().wait()
        session._sleep=fake_sleep
        async def sleeper():await asyncio.sleep(3600)
        old=asyncio.create_task(sleeper())
        session._ticker=old
        await session.handle({'type':'extend_settings','backchannel_s':10,'offer_hint_s':12,'max_wait_s':60})
        await asyncio.sleep(0)
        self.assertTrue(old.cancelled())
        self.assertIsNot(session._ticker,old)
        self.assertEqual(session.engine.controller.silence_started,since)
        await asyncio.wait_for(sleeping.wait(),timeout=2)
        self.assertEqual(delays,[5.0])  # backchannel at t=10, not t=5+10 or old t=4.

    async def test_paused_or_resting_update_does_not_start_silence(self):
        await self.session.handle({'type':'rest'})
        await self.session.handle({'type':'extend_settings','max_wait_s':60})
        self.assertTrue(self.session._resting)
        self.assertIsNone(self.session._ticker)
