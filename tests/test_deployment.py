"""Deployment boundaries: liveness, entrypoint options, and synthetic probe auth."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from patient_listener.app.server import create_app
from patient_listener.config import Settings


class DeploymentTests(unittest.TestCase):
    def test_false_reload_does_not_enable_reloader(self):
        from patient_listener.app.__main__ import main
        with patch.dict(os.environ, {'PL_RELOAD':'false','PL_HOST':'0.0.0.0','PL_PORT':'8000'}), patch('uvicorn.run') as run:
            main()
        self.assertFalse(run.call_args.kwargs['reload'])
        self.assertFalse(run.call_args.kwargs['proxy_headers'])
        self.assertEqual(run.call_args.kwargs['host'], '0.0.0.0')

    def test_liveness_does_not_promote_voice_health(self):
        from types import SimpleNamespace
        cfg = Settings(ai_enabled=False, voice_enabled=True, nebius_api_key='')
        with patch('patient_listener.app.voice_runtime.VoiceRuntime.load', return_value=SimpleNamespace(close=lambda:None)):
            with TestClient(create_app(cfg)) as client:
                self.assertEqual(client.get('/livez').status_code,200)
                health = client.get('/healthz')
                self.assertEqual(health.status_code,503)
                self.assertFalse(health.json()['streaming_ready'])

    def probe(self):
        path=Path(__file__).resolve().parents[1]/'deploy'/'websocket_probe.py'
        spec=importlib.util.spec_from_file_location('probe_under_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.dict(os.environ, {'PL_PROBE_TOKEN':'x'*48}):
            return module.create_app()

    def test_probe_echoes_synthetic_binary_and_rejects_invalid_credentials(self):
        with TestClient(self.probe()) as client:
            self.assertEqual(client.get('/livez').json()['status'],'synthetic_probe_only')
            for headers in ({}, {'Authorization':'Bearer wrong'}):
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect('/echo',headers=headers):
                        self.fail('Unauthenticated echo accepted')
            with client.websocket_connect('/echo',headers={'Authorization':'Bearer '+'x'*48}) as ws:
                ws.send_bytes(b'synthetic-ping')
                self.assertEqual(ws.receive_bytes(),b'synthetic-ping')
                ws.send_bytes(b'x'*65)
                self.assertEqual(ws.receive()['code'],1009)

    def test_probe_requires_explicit_disposable_credential(self):
        path=Path(__file__).resolve().parents[1]/'deploy'/'websocket_probe.py'
        spec=importlib.util.spec_from_file_location('probe_no_token',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.dict(os.environ, {'PL_PROBE_TOKEN':''}):
            with self.assertRaises(ValueError):module.create_app()

    def test_short_echo_run_cannot_claim_full_gate(self):
        from patient_listener.tools.websocket_check import summary, validate_url
        self.assertFalse(summary([10,20,30],2,2,'local')['g02_location_pass'])
        self.assertTrue(summary([10,20,30],600.1,600,'Pakistan')['g02_location_pass'])
        self.assertFalse(summary([10,201],600.1,600,'UK')['g02_location_pass'])
        self.assertFalse(summary([10,20],600.1,600,'local')['g02_location_pass'])
        self.assertEqual(validate_url('ws://127.0.0.1:8000/echo'),'ws://127.0.0.1:8000/echo')
        for url in ['ws://cloud.example/echo','wss://user:secret@cloud.example/echo','wss://cloud.example/echo?token=secret']:
            with self.assertRaises(ValueError):validate_url(url)
