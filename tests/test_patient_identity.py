"""Authenticated patient discovery and reconnects without selecting another persona."""
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from patient_listener.app.server import create_app
from patient_listener.config import Settings
from patient_listener.types import Need

DEVICE='a'*48


class PatientIdentityTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(create_app(Settings(ai_enabled=False,nebius_api_key='',
            voice_enabled=False,patient_enrollment_required=True,console_demo_enabled=False)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.store=self.client.app.state.pl.store
        self.store.add_person('demo-amina','Amina',frozenset({Need.SAVING_ENERGY}))
        self.store.set_console_user('sam','Sam','therapist')
        for pid in ('demo-margaret','demo-joseph','demo-amina'):
            self.store.link_console_user('sam',pid)
        self.sam={'Authorization':'Bearer '+self.store.issue_console_token('sam')}
        self.device={'X-PL-Device':DEVICE}

    def enroll(self,pid='demo-joseph'):
        result=self.client.post('/api/console/patients/'+pid+'/device-links',headers=self.sam)
        self.assertEqual(result.status_code,200)
        result=self.client.post('/api/patient/enroll',headers=self.device,
                               json={'setup_code':result.json()['setup_code']})
        self.assertEqual(result.status_code,200)
        return result.json()

    def me(self,headers=None,path='/api/session/me'):
        return self.client.get(path,headers=self.device if headers is None else headers)

    def test_joseph_identity_and_needs_survive_repeated_page_loads(self):
        self.enroll()
        for _ in range(5):
            result=self.me()
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['cache-control'],'no-store')
            data=result.json()
            self.assertEqual(data['person_id'],'demo-joseph')
            self.assertEqual(data['name'],'Joseph')
            self.assertEqual(data['needs'],['being_heard'])
            self.assertEqual(data['settings']['needs'],['being_heard'])
            self.assertNotIn('token',data)
            self.assertNotIn('credential',data)

    def test_query_and_client_role_cannot_change_enrolled_person(self):
        self.enroll()
        result=self.me(path='/api/session/me?person=margaret&role=therapist')
        self.assertEqual(result.json()['person_id'],'demo-joseph')
        result=self.client.get('/api/session?person=margaret',headers=self.device)
        self.assertEqual(result.status_code,401)

    def test_unenrolled_and_missing_or_wrong_device_are_denied(self):
        self.assertEqual(self.me().status_code,401)
        self.assertEqual(self.me(headers=self.sam).status_code,401)
        self.enroll()
        for device in ('','short','b'*48,'! * invalid device'):
            result=self.me(headers={'X-PL-Device':device})
            self.assertEqual(result.status_code,401)
            self.assertEqual(result.headers['cache-control'],'no-store')

    def test_missing_or_forged_cookie_is_denied_even_with_valid_helper_token(self):
        self.enroll()
        self.client.cookies.clear()
        self.assertEqual(self.me(headers={**self.device,**self.sam}).status_code,401)
        self.client.cookies.set('pl_patient_link','fake-cookie-'+'x'*40,path='/api/session')
        self.assertEqual(self.me().status_code,401)

    def test_new_custom_person_and_saved_combined_needs_are_returned_without_alias_mapping(self):
        self.enroll('demo-amina')
        self.assertEqual(self.me().json()['needs'],['saving_energy'])
        self.store.console_update_profile('demo-amina',
            {'needs':['saving_energy','being_clear'],'max_wait_s':60},actor='sam')
        data=self.me().json()
        self.assertEqual(data['person_id'],'demo-amina')
        self.assertEqual(data['needs'],['being_clear','saving_energy'])
        self.assertEqual(data['settings']['max_wait_s'],60)

    def test_revoked_and_expired_devices_cannot_discover_identity(self):
        result=self.enroll()
        self.client.delete('/api/console/patients/demo-joseph/devices/'+result['authorization_id'],headers=self.sam)
        self.assertEqual(self.me().status_code,401)
        self.enroll()
        self.store._db.execute("UPDATE patient_devices SET expires_at='2000-01-01T00:00:00+00:00'")
        self.store._db.commit()
        self.assertEqual(self.me().status_code,401)

    def test_deleted_patient_is_not_returned(self):
        self.enroll()
        self.store.delete_all('demo-joseph')
        self.assertEqual(self.me().status_code,401)

    def test_identity_endpoint_does_not_start_practice_or_call_models(self):
        self.enroll()
        with patch('patient_listener.app.server.build_llm',side_effect=AssertionError('No inference')):
            self.assertEqual(self.me().status_code,200)
        registry=self.client.app.state.pl.sessions
        self.assertFalse(self.client.portal.call(registry.active,'demo-joseph'))
        self.assertFalse(self.client.portal.call(registry.active,'__gpu_voice__'))
        self.assertEqual(self.store.attempts_for('demo-joseph'),[])

    def test_https_required_and_proxy_tls_recognized(self):
        self.enroll()
        self.client.app.state.settings=replace(self.client.app.state.settings,require_https=True)
        self.assertEqual(self.me().status_code,400)
        self.client.app.state.settings=replace(self.client.app.state.settings,trust_proxy_headers=True)
        self.assertEqual(self.me(headers={**self.device,'X-Forwarded-Proto':'https'}).status_code,200)

    def test_authenticated_disconnect_allows_repeat_text_session_without_reenrollment(self):
        self.enroll()
        for _ in range(4):
            result=self.client.get('/api/session?person=demo-joseph',headers=self.device)
            self.assertEqual(result.status_code,200)
            with self.client.websocket_connect('/ws?token='+result.json()['token']+'&device='+DEVICE) as ws:
                ws.send_json({'type':'get_settings'})
                self.assertEqual(ws.receive_json()['type'],'settings')
            self.assertFalse(self.client.portal.call(self.client.app.state.pl.sessions.active,'demo-joseph'))
            self.assertEqual(self.me().status_code,200)
