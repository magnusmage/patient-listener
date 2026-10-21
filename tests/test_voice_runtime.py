"""GPU lifetime and truthful readiness checks, without model downloads."""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.config import Settings


class VoiceRuntimeTests(unittest.TestCase):
    def test_text_mode_never_loads_gpu_models(self):
        with patch('patient_listener.app.server.VoiceRuntime.load') as load:
            with TestClient(create_app(Settings(voice_enabled=False))) as client:
                response = client.get('/healthz')
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()['models_loaded'])
            load.assert_not_called()

    def test_models_loaded_once_and_released_on_shutdown(self):
        runtime = MagicMock()
        with patch('patient_listener.app.server.VoiceRuntime.load', return_value=runtime) as load:
            with TestClient(create_app(Settings(voice_enabled=True))) as client:
                for _ in range(2):
                    response = client.get('/healthz')
                    self.assertEqual(response.status_code, 503)
                    self.assertTrue(response.json()['models_loaded'])
                    self.assertFalse(response.json()['streaming_ready'])
                load.assert_called_once()
                runtime.close.assert_not_called()
            runtime.close.assert_called_once()

    def test_model_loading_failure_fails_startup(self):
        with patch('patient_listener.app.server.VoiceRuntime.load', side_effect=RuntimeError('GPU unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'GPU unavailable'):
                with TestClient(create_app(Settings(voice_enabled=True))):
                    pass
