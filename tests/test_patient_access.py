"""Patient authorization and setup use only synthetic databases; no model calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from patient_listener.app.server import create_app
from patient_listener.app.tokens import TokenSigner
from patient_listener.config import Settings
from patient_listener.store.patient_access import PatientAccess, key
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all

PID='demo-margaret'
DEVICE='a'*48


class PatientApiTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(create_app(Settings(ai_enabled=False,voice_enabled=False,nebius_api_key='',
            patient_enrollment_required=True,console_demo_enabled=True)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.store=self.client.app.state.pl.store
        self.sam=self.helper('sam','therapist',PID)
        self.alex=self.helper('alex','carer',PID)

    def helper(self,name,role,pid):
        self.store.set_console_user(name,name,role)
        self.store.link_console_user(name,pid)
        return {'Authorization':'Bearer '+self.store.issue_console_token(name)}

    def invite(self,headers=None,person='margaret'):
        return self.client.post('/api/console/patients/'+person+'/device-links',headers=self.sam if headers is None else headers)

    def enroll(self,device=DEVICE):
        invite=self.invite().json()
        result=self.client.post('/api/patient/enroll',json={'setup_code':invite['setup_code']},headers={'X-PL-Device':device})
        self.assertEqual(result.status_code,200)
        return result

    def session(self,device=DEVICE,person='margaret'):
        return self.client.get('/api/session',params={'person':person},headers={'X-PL-Device':device})

    def test_alias_device_and_fake_role_are_not_authorization(self):
        for person in ('margaret','demo-margaret','unknown'):
            self.assertEqual(self.session(person=person).status_code,401)
        result=self.client.get('/api/session?person=margaret',headers={'X-PL-Device':DEVICE,'X-Role':'therapist',**self.sam})
        self.assertEqual(result.status_code,401)
        self.assertEqual(self.invite({}).status_code,401)

    def test_only_linked_real_helpers_can_issue_list_or_revoke(self):
        other=self.helper('other','therapist','demo-joseph')
        agent=self.helper('agent','agent',PID)
        demo=self.client.post('/api/console/demo/session').json()['token']
        for headers,code in [(other,404),(agent,403),({'Authorization':'Bearer '+demo},403)]:
            self.assertEqual(self.invite(headers).status_code,code)
            self.assertEqual(self.client.get('/api/console/patients/margaret/devices',headers=headers).status_code,code)
        self.assertEqual(self.invite(self.alex).status_code,200)

    def test_setup_code_single_use_cookie_private_and_only_hashes_stored(self):
        invite=self.invite().json()
        code=invite['setup_code']
        self.assertEqual(self.store._db.execute('SELECT code_hash FROM patient_invites').fetchone()[0],key(code))
        result=self.client.post('/api/patient/enroll',json={'setup_code':code},headers={'X-PL-Device':DEVICE})
        self.assertEqual(result.status_code,200)
        self.assertNotIn('credential',result.json())
        self.assertEqual(result.headers['cache-control'],'no-store')
        cookie=result.headers['set-cookie']
        self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=strict',cookie)
        self.assertIn('Path=/api/session',cookie)
        secret=self.client.cookies.get('pl_patient_link')
        row=self.store._db.execute('SELECT * FROM patient_devices').fetchone()
        self.assertEqual(row['secret_hash'],key(secret))
        self.assertNotIn(secret,str(dict(row))+str(self.store.audit_log()))
        self.assertNotIn(DEVICE,str(dict(row)))
        self.assertEqual(self.client.post('/api/patient/enroll',json={'setup_code':code},headers={'X-PL-Device':DEVICE}).status_code,400)
        response=self.session()
        self.assertEqual(response.status_code,200)
        token=response.json()['token']
        claims=self.client.app.state.pl.signer.verify(token,DEVICE)
        self.assertEqual(claims.authorization_id,result.json()['authorization_id'])
        self.assertEqual(self.session(device='b'*48).status_code,401)
        self.assertEqual(self.session(person='joseph').status_code,401)
        with self.client.websocket_connect('/ws?token='+token+'&device='+DEVICE) as ws:
            ws.send_json({'type':'start'})
            self.assertEqual(ws.receive_json()['type'],'greeting')

    def test_legacy_signed_token_cannot_bypass_required_enrollment(self):
        token=self.client.app.state.pl.signer.issue(PID,DEVICE)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws?token='+token+'&device='+DEVICE):
                self.fail('Legacy token accepted without device enrollment')

    def test_revoke_blocks_renewal_and_previously_minted_socket_token(self):
        enrollment=self.enroll().json()
        token=self.session().json()['token']
        aid=enrollment['authorization_id']
        result=self.client.delete('/api/console/patients/margaret/devices/'+aid,headers=self.alex)
        self.assertTrue(result.json()['revoked'])
        self.assertEqual(self.session().status_code,401)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws?token='+token+'&device='+DEVICE):
                self.fail('Revoked authorization accepted')

    def test_relink_same_device_invalidates_old_socket_token(self):
        old=self.enroll().json()['authorization_id']
        token=self.session().json()['token']
        new=self.enroll().json()['authorization_id']
        self.assertNotEqual(old,new)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM patient_devices').fetchone()[0],1)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws?token='+token+'&device='+DEVICE):
                self.fail('Old device generation accepted')

    def test_invalid_and_expired_codes_and_payloads_do_not_enroll(self):
        code=self.invite().json()['setup_code']
        self.store._db.execute("UPDATE patient_invites SET expires_at='2000-01-01T00:00:00+00:00'");self.store._db.commit()
        for value in (code,'x'*43):
            self.assertEqual(self.client.post('/api/patient/enroll',json={'setup_code':value},headers={'X-PL-Device':DEVICE}).status_code,400)
        for payload in ({},{'setup_code':'x'*43,'person_id':PID},{'setup_code':123}):
            self.assertEqual(self.client.post('/api/patient/enroll',json=payload,headers={'X-PL-Device':DEVICE}).status_code,422)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM patient_devices').fetchone()[0],0)

    def test_secure_cookie_and_https_enrollment_guard(self):
        from dataclasses import replace
        self.client.app.state.settings=replace(self.client.app.state.settings,require_https=True)
        code=self.invite().json().get('setup_code')
        self.assertIsNone(code)
        setup=PatientAccess(self.store).create_invite(PID,'sam')['setup_code']
        self.assertEqual(self.client.post('/api/patient/enroll',json={'setup_code':setup},headers={'X-PL-Device':DEVICE}).status_code,400)
        result=self.client.post('https://testserver/api/patient/enroll',json={'setup_code':setup},headers={'X-PL-Device':DEVICE})
        self.assertEqual(result.status_code,200)
        self.assertIn('Secure',result.headers['set-cookie'])


class PatientStoreTests(unittest.TestCase):
    def setUp(self):
        self.store=SqliteStore()
        self.addCleanup(self.store.close)
        seed_all(self.store)
        self.store.set_console_user('sam','Sam','therapist')
        self.store.link_console_user('sam',PID)
        self.access=PatientAccess(self.store)

    def test_production_cannot_disable_enrollment_but_local_demo_is_explicitly_compatible(self):
        self.assertTrue(Settings(environment='production',patient_enrollment_required=False).requires_patient_enrollment)
        self.assertTrue(Settings(environment='development',patient_enrollment_required=True).requires_patient_enrollment)
        self.assertFalse(Settings(environment='development',patient_enrollment_required=False).requires_patient_enrollment)

    def test_helper_unlink_and_new_invite_invalidate_old_setup(self):
        old=self.access.create_invite(PID,'sam')['setup_code']
        current=self.access.create_invite(PID,'sam')['setup_code']
        with self.assertRaises(ValueError):self.access.redeem(old,DEVICE)
        self.store._db.execute('DELETE FROM console_links WHERE user_id=?',('sam',));self.store._db.commit()
        with self.assertRaises(KeyError):self.access.redeem(current,DEVICE)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM patient_devices').fetchone()[0],0)

    def test_redeem_rollback_keeps_old_device_and_invite(self):
        first=self.access.redeem(self.access.create_invite(PID,'sam')['setup_code'],DEVICE)
        code=self.access.create_invite(PID,'sam')['setup_code']
        self.store._db.execute("CREATE TRIGGER reject_device BEFORE INSERT ON patient_devices BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(Exception):self.access.redeem(code,DEVICE)
        self.assertEqual(self.access.credential_authorization(PID,DEVICE,first['credential']),first['authorization_id'])
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM patient_invites').fetchone()[0],1)

    def test_expiry_and_delete_remove_patient_access(self):
        linked=self.access.redeem(self.access.create_invite(PID,'sam')['setup_code'],DEVICE)
        self.access.create_invite(PID,'sam')
        self.assertTrue(self.access.active(PID,DEVICE,linked['authorization_id']))
        self.store._db.execute("UPDATE patient_devices SET expires_at='2000-01-01T00:00:00+00:00'");self.store._db.commit()
        self.assertFalse(self.access.active(PID,DEVICE,linked['authorization_id']))
        self.store.delete_all(PID)
        for table in ('patient_devices','patient_invites'):
            self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)

    def test_credential_persists_on_reopen_and_double_redemption_has_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'devices.db')
            first=SqliteStore(path,check_same_thread=False);seed_all(first)
            first.set_console_user('sam','Sam','therapist');first.link_console_user('sam',PID)
            code=PatientAccess(first).create_invite(PID,'sam')['setup_code']
            second=SqliteStore(path,check_same_thread=False)
            try:
                def redeem(store):
                    try:return PatientAccess(store).redeem(code,DEVICE)
                    except ValueError:return None
                with ThreadPoolExecutor(2) as pool:
                    a=pool.submit(redeem,first);b=pool.submit(redeem,second)
                    results=[a.result(),b.result()]
                self.assertEqual(sum(r is not None for r in results),1)
                linked=next(r for r in results if r)
            finally:first.close();second.close()
            reopened=SqliteStore(path)
            try:self.assertEqual(PatientAccess(reopened).credential_authorization(PID,DEVICE,linked['credential']),linked['authorization_id'])
            finally:reopened.close()

    def test_binding_is_signed_and_not_a_client_editable_claim(self):
        signer=TokenSigner('synthetic-secret')
        token=signer.issue(PID,DEVICE,authorization_id='plauth_example')
        with self.assertRaises(ValueError):signer.verify(token.replace('plauth_example','plauth_changed'),DEVICE)
        self.assertEqual(signer.verify(token,DEVICE).authorization_id,'plauth_example')


class PatientCliTests(unittest.TestCase):
    def test_actual_local_http_cookie_enrollment_and_revocation(self):
        import io
        import socket
        import threading
        import time
        import uvicorn
        from patient_listener.tools.patient_access_check import main
        cfg=Settings(ai_enabled=False,voice_enabled=False,nebius_api_key='',patient_enrollment_required=True)
        app=create_app(cfg)
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='critical',access_log=False))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+10
            while not server.started:
                if not thread.is_alive() or time.monotonic()>deadline:self.fail('Local test server failed to start')
                time.sleep(.01)
            store=app.state.pl.store
            store.set_console_user('sam','Sam','therapist');store.link_console_user('sam',PID)
            helper=store.issue_console_token('sam')
            with patch('patient_listener.tools.patient_access_check.getpass.getpass',return_value=helper),patch('sys.stdout',new_callable=io.StringIO) as output:
                result=main(['--port',str(port)])
                text=output.getvalue()
            self.assertEqual(result,0,text)
            self.assertNotIn(helper,text)
            self.assertNotIn('pldevice_',text)
            self.assertEqual(store._db.execute('SELECT COUNT(*) FROM patient_devices').fetchone()[0],0)
            self.assertTrue(store.person_exists(PID))
            self.assertEqual(len(store.all_words(PID)),4)
            with patch('patient_listener.tools.patient_access_check.getpass.getpass',return_value='invalid-console-token'),patch('sys.stdout',new_callable=io.StringIO) as output:
                result=main(['--port',str(port)])
                text=output.getvalue()
            self.assertEqual(result,1)
            self.assertIn('helper authentication (HTTP 401)',text)
            self.assertNotIn('invalid-console-token',text)
            self.assertEqual(store._db.execute('SELECT COUNT(*) FROM patient_devices').fetchone()[0],0)
        finally:
            server.should_exit=True
            thread.join(timeout=5)
            sock.close()
