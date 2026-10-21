"""Authenticated voice lifecycle and GPU slot cleanup without optional GPU dependencies."""
import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.config import Settings


class FakeConnection:
    def __init__(self, runtime, session, socket, send): self.send = send
    async def start(self): pass
    async def close(self): pass
    async def frame(self, data): pass
    def acknowledge(self, value): pass


class VoiceAccessTests(unittest.TestCase):
    DEVICE = 'a'*48

    def url(self, client, person):
        token = client.get('/api/session',params={'person':person},
                           headers={'X-PL-Device':self.DEVICE}).json()['token']
        return f'/ws?token={token}&device={self.DEVICE}&voice=true'

    def test_disconnect_releases_patient_and_gpu_for_reconnect(self):
        with patch('patient_listener.app.server.VoiceRuntime.load',return_value=MagicMock()), patch(
            'patient_listener.app.server.VoiceConnection',FakeConnection):
            with TestClient(create_app(Settings(voice_enabled=True))) as client:
                with client.websocket_connect(self.url(client,'margaret')) as first:
                    first.send_json({'type':'start'})
                    self.assertEqual(first.receive_json()['type'],'greeting')
                    with self.assertRaises(Exception):
                        with client.websocket_connect(self.url(client,'daniyal')): pass
                for person in ('margaret','daniyal'):
                    with client.websocket_connect(self.url(client,person)) as ws:
                        ws.send_json({'type':'start'})
                        self.assertEqual(ws.receive_json()['type'],'greeting')

    def test_failed_voice_initialization_does_not_leak_gpu_slot(self):
        class BrokenConnection(FakeConnection):
            async def start(self): raise RuntimeError('adapter failed')
        with patch('patient_listener.app.server.VoiceRuntime.load',return_value=MagicMock()):
            with TestClient(create_app(Settings(voice_enabled=True))) as client:
                with patch('patient_listener.app.server.VoiceConnection',BrokenConnection):
                    with self.assertRaises(RuntimeError):
                        with client.websocket_connect(self.url(client,'margaret')) as ws:
                            ws.receive_json()
                with patch('patient_listener.app.server.VoiceConnection',FakeConnection):
                    with client.websocket_connect(self.url(client,'daniyal')) as ws:
                        ws.send_json({'type':'start'})
                        self.assertEqual(ws.receive_json()['type'],'greeting')
