"""CPU/GPU boundaries with synthetic runtimes and a shared disposable SQLite DB."""
import asyncio
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from patient_listener.app.server import create_app
from patient_listener.app.remote_voice import RemoteRenderer,RemoteRenderError,contract,MAX_PCM
from patient_listener.app.session_registry import DatabaseSessionRegistry
from patient_listener.config import Settings
from patient_listener.store.leases import LeaseStore
from patient_listener.store.sqlite_store import SqliteStore

PID='demo-margaret'
DEVICE='a'*48
SIGNING='s'*48
SERVICE='r'*48
ORIGIN='http://127.0.0.1:18000'


def cfg(path,role):
    return Settings(database_url='sqlite:///'+path,service_role=role,ai_enabled=False,
        nebius_api_key='',voice_enabled=role=='voice',session_token_secret=SIGNING,
        voice_service_secret=SERVICE,voice_public_ws_url='ws://127.0.0.1:18001/ws',
        voice_internal_url='http://127.0.0.1:18001',voice_allowed_origins=(ORIGIN,))


class SplitApiTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        path=str(Path(self.directory.name)/'shared.db')
        self.api=TestClient(create_app(cfg(path,'api')),base_url=ORIGIN)
        self.api.__enter__();self.addCleanup(self.api.__exit__,None,None,None)
        self.runtime=SimpleNamespace(gpu_lock=threading.Lock(),close=lambda:None)
        loader=patch('patient_listener.app.voice_runtime.VoiceRuntime.load',return_value=self.runtime)
        loader.start();self.addCleanup(loader.stop)
        self.voice=TestClient(create_app(cfg(path,'voice')))
        self.voice.__enter__();self.addCleanup(self.voice.__exit__,None,None,None)
        store=self.api.app.state.pl.store
        store.set_console_user('sam','Sam','therapist');store.link_console_user('sam',PID)
        self.helper={'Authorization':'Bearer '+store.issue_console_token('sam')}
        code=self.api.post('/api/console/patients/margaret/device-links',headers=self.helper).json()['setup_code']
        self.assertEqual(self.api.post('/api/patient/enroll',json={'setup_code':code},headers={'X-PL-Device':DEVICE}).status_code,200)

    def token(self,voice=True):
        result=self.api.get('/api/session',params={'person':'margaret','voice':voice},headers={'X-PL-Device':DEVICE})
        self.assertEqual(result.status_code,200)
        return result.json()

    def test_cpu_has_no_models_routes_voice_separately_and_preserves_text_route(self):
        self.assertIsNone(self.api.app.state.voice_runtime)
        self.assertEqual(self.token()['ws_url'],'ws://127.0.0.1:18001/ws')
        self.assertTrue(self.token()['voice_enabled'])
        self.assertEqual(self.token(False)['ws_url'],ORIGIN.replace('http','ws')+'/ws')
        self.assertEqual(self.voice.get('/api/console/me',headers=self.helper).status_code,404)
        self.assertEqual(self.voice.get('/api/session',headers={'X-PL-Device':DEVICE}).status_code,404)
        self.assertEqual(self.voice.get('/').status_code,404)
        self.assertIn(self.api.post('/internal/render',json={}).status_code,(404,405))
        self.assertEqual(self.voice.get('/healthz').status_code,503)

    def test_signed_cpu_token_works_on_voice_and_blocks_cpu_deletion(self):
        token=self.token()['token']
        for origin in ('http://untrusted.example',None):
            with self.assertRaises(WebSocketDisconnect):
                with self.voice.websocket_connect('/ws?token='+token+'&device='+DEVICE,
                        headers={} if origin is None else {'Origin':origin}):
                    self.fail('Untrusted browser origin accepted')
        with self.voice.websocket_connect('/ws?token='+token+'&device='+DEVICE,headers={'Origin':ORIGIN}) as ws:
            ws.send_json({'type':'start'})
            self.assertEqual(ws.receive_json()['type'],'greeting')
            response=self.api.post('/api/console/privacy/margaret/deletion-request',headers=self.helper)
            self.assertEqual(response.status_code,409)
        self.assertEqual(self.api.post('/api/console/privacy/margaret/deletion-request',headers=self.helper).status_code,200)

    def test_renderer_requires_service_key_live_person_lease_and_matching_contract(self):
        registry=self.api.app.state.pl.sessions
        self.assertTrue(self.api.portal.call(registry.claim,PID))
        try:
            body={'person_id':PID,'lease_owner':registry.owner(PID),'text':'A family pet.',
                  'contract':contract(self.api.app.state.settings)}
            self.assertEqual(self.voice.post('/internal/render',json=body).status_code,401)
            headers={'X-PL-Service-Key':SERVICE}
            self.assertEqual(self.voice.post('/internal/render',json={**body,'lease_owner':'x'*43},headers=headers).status_code,409)
            self.assertEqual(self.voice.post('/internal/render',json={**body,'contract':'0'*64},headers=headers).status_code,409)
            with patch('patient_listener.app.nemo_stream.render_hint',return_value=b'\x01\x00'*20):
                response=self.voice.post('/internal/render',json=body,headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content,b'\x01\x00'*20)
            self.assertEqual(response.headers['x-pl-audio-contract'],body['contract'])
            self.voice.portal.call(self.voice.app.state.pl.sessions.claim,'__gpu_voice__')
            try:self.assertEqual(self.voice.post('/internal/render',json=body,headers=headers).status_code,409)
            finally:self.voice.portal.call(self.voice.app.state.pl.sessions.release,'__gpu_voice__')
        finally:self.api.portal.call(registry.release,PID)

    def test_real_http_remote_renderer_publishes_without_cpu_gpu_imports(self):
        import socket
        import time
        import uvicorn
        path=str(Path(self.directory.name)/'shared.db')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        app=create_app(cfg(path,'voice'))
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='critical',access_log=False))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+10
            while not server.started:
                if not thread.is_alive() or time.monotonic()>deadline:self.fail('Synthetic voice service failed to start')
                time.sleep(.01)
            updated=replace(self.api.app.state.settings,voice_internal_url=f'http://127.0.0.1:{port}')
            self.api.app.state.settings=updated;self.api.app.state.pl.settings=updated
            with patch('patient_listener.app.nemo_stream.render_hint',return_value=b'\x01\x00'*20):
                result=self.api.post('/api/console/plans/margaret/generate',headers=self.helper,
                    json={'max_words':1,'use_ai':False,'render_audio':True})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['rendered_clips'],3)
            self.assertIsNone(self.api.app.state.voice_runtime)
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()

    def test_wrong_signing_secret_rejects_api_token_on_voice(self):
        token=self.token()['token']
        from patient_listener.app.tokens import TokenSigner
        self.voice.app.state.pl.signer=TokenSigner('different-secret')
        with self.assertRaises(WebSocketDisconnect):
            with self.voice.websocket_connect('/ws?token='+token+'&device='+DEVICE,headers={'Origin':ORIGIN}):
                self.fail('Wrong signer accepted')

    def test_cpu_plan_generation_publishes_all_remote_clips_without_loading_gpu(self):
        from urllib.error import HTTPError
        from io import BytesIO
        from patient_listener.app.remote_voice import RemoteRenderer
        api=self.api
        voice=self.voice
        def fetch(renderer,text):
            result=voice.post('/internal/render',headers={'X-PL-Service-Key':SERVICE},json={
                'person_id':renderer.person_id,'lease_owner':renderer.registry.owner(renderer.person_id),
                'text':text,'contract':contract(renderer.settings)})
            if result.status_code!=200:raise RemoteRenderError()
            return result.content
        with patch.object(RemoteRenderer,'_fetch',fetch),patch('patient_listener.app.nemo_stream.render_hint',return_value=b'\x01\x00'*20) as synth:
            result=api.post('/api/console/plans/margaret/generate',headers=self.helper,
                json={'max_words':1,'use_ai':False,'render_audio':True})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['rendered_clips'],3)
        self.assertEqual(synth.call_count,3)
        self.assertIsNone(api.app.state.voice_runtime)


class LeaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path=str(Path(self.temp.name)/'leases.db')
        initial=SqliteStore(path);initial.close()
        self.a=LeaseStore(sqlite3.connect(path,check_same_thread=False))
        self.b=LeaseStore(sqlite3.connect(path,check_same_thread=False))
        self.addCleanup(self.a.close);self.addCleanup(self.b.close)

    async def test_only_one_worker_owns_person_and_stale_owner_cannot_release_new_lease(self):
        self.assertTrue(self.a.claim(PID,'first',90))
        self.assertFalse(self.b.claim(PID,'second',90))
        self.a.db.execute('UPDATE session_leases SET expires_at=0');self.a.db.commit()
        self.assertTrue(self.b.claim(PID,'second',90))
        self.assertFalse(self.a.renew(PID,'first',90))
        self.a.release(PID,'first')
        self.assertTrue(self.b.owns(PID,'second'))
        self.assertNotIn(PID,str(self.a.db.execute('SELECT * FROM session_leases').fetchall()))

    async def test_heartbeat_loss_cancels_owner_and_records_lost_admission(self):
        registry=DatabaseSessionRegistry(self.a)
        registry.INTERVAL=.01
        started=asyncio.Event()
        async def operation():
            self.assertTrue(await registry.claim(PID))
            started.set()
            try:await asyncio.Event().wait()
            finally:await registry.release(PID)
        with patch.object(self.a,'renew',return_value=False):
            task=asyncio.create_task(operation())
            await started.wait()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,1)
        self.assertTrue(registry.was_lost(PID))
        self.assertFalse(self.b.active(PID))


class SplitSettingsTests(unittest.TestCase):
    def test_invalid_roles_urls_and_secrets_fail_before_serving(self):
        base=cfg('/tmp/nonexistent-test.db','api')
        for changes in ({'service_role':'typo'},{'session_token_secret':''},{'voice_service_secret':SIGNING},
            {'voice_public_ws_url':'ws://public.example/ws'},{'voice_internal_url':'http://public.example'},
            {'voice_public_ws_url':'wss://user:secret@public.example/ws'},
            {'voice_internal_url':'https://public.example?key=secret'}, {'voice_enabled':True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):replace(base,**changes).assert_safe_startup()
        with self.assertRaises(ValueError):
            with TestClient(create_app(replace(base,database_url='sqlite:///:memory:'))):pass


class RemoteClientTests(unittest.TestCase):
    def test_wire_contract_rejects_wrong_metadata_oversize_and_redirects(self):
        import io
        from urllib.error import HTTPError
        from unittest.mock import MagicMock
        settings=cfg('/tmp/fake.db','api')
        registry=SimpleNamespace(owner=lambda pid:'o'*43)
        renderer=RemoteRenderer(settings,registry,PID)
        opener=MagicMock()
        expected=contract(settings)
        for headers,pcm,valid in [
            ({'Content-Type':'application/octet-stream','X-PL-Audio-Contract':expected},b'\x01\x00'*10,True),
            ({'Content-Type':'text/html','X-PL-Audio-Contract':expected},b'xx',False),
            ({'Content-Type':'application/octet-stream','X-PL-Audio-Contract':'0'*64},b'xx',False),
            ({'Content-Type':'application/octet-stream','X-PL-Audio-Contract':expected},b'x'*(MAX_PCM+2),False)]:
            response=MagicMock();response.__enter__.return_value=response
            response.headers=headers;response.read.side_effect=io.BytesIO(pcm).read
            opener.open.return_value=response
            with patch('patient_listener.app.remote_voice.build_opener',return_value=opener):
                if valid:self.assertEqual(renderer._fetch('A family pet.'),pcm)
                else:
                    with self.assertRaises(RemoteRenderError):renderer._fetch('A family pet.')
        request=opener.open.call_args.args[0]
        self.assertNotIn(SERVICE,request.full_url)
        self.assertEqual(request.get_header('X-pl-service-key'),SERVICE)
        opener.open.side_effect=HTTPError('http://127.0.0.1:18001/internal/render',302,'redirect',{},None)
        with patch('patient_listener.app.remote_voice.build_opener',return_value=opener):
            with self.assertRaises(RemoteRenderError):renderer._fetch('A family pet.')


class ServiceLauncherTests(unittest.TestCase):
    def test_private_common_config_is_not_overwritten_and_both_roles_validate(self):
        import io
        import os
        from patient_listener.tools.services import main
        from dotenv import dotenv_values
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'existing.db';db.touch()
            env=Path(directory)/'.env.split'
            with patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(main(['init','--db',str(db),'--out',str(env)]),0)
            original=env.read_text()
            values=dotenv_values(env,interpolate=False)
            self.assertNotEqual(values['SESSION_TOKEN_SECRET'],values['VOICE_SERVICE_SECRET'])
            with patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit):main(['init','--db',str(db),'--out',str(env)])
            self.assertEqual(env.read_text(),original)
            for role in ('api','voice'):
                with patch.dict(os.environ,{},clear=True),patch('sys.stdout',new_callable=io.StringIO) as output:
                    self.assertEqual(main(['check',role,'--env-file',str(env)]),0)
                    self.assertNotIn(values['VOICE_SERVICE_SECRET'],output.getvalue())
            with patch.dict(os.environ,{'SESSION_TOKEN_SECRET':'conflicting-secret'},clear=True),patch('sys.stderr',new_callable=io.StringIO) as error:
                with self.assertRaises(SystemExit):main(['check','api','--env-file',str(env)])
                self.assertIn('SESSION_TOKEN_SECRET',error.getvalue())
                self.assertNotIn('conflicting-secret',error.getvalue())
