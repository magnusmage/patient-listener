"""Warm-up/readiness contracts with fakes only; no CUDA or paid calls."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.app.voice_warmup import warm_up
from patient_listener.config import Settings


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(fixed_clips={str(i): b'\0\0' for i in range(10)},
                                       settings=Settings())
        self.stream = SimpleNamespace(buffer=SimpleNamespace(step=1),
            feed=MagicMock(), decode=MagicMock(), reset_stream=MagicMock())
        self.factory = MagicMock(return_value=self.stream)
        self.cuda = SimpleNamespace(synchronize=MagicMock())
        self.modules = {'torch': SimpleNamespace(inference_mode=nullcontext, cuda=self.cuda),
                        'numpy': SimpleNamespace(zeros=lambda size, dtype: ('synthetic', size), float32='f32')}

    def run_warmup(self):
        with patch.dict('sys.modules', self.modules):
            return warm_up(self.runtime, stream_factory=self.factory)

    def test_exercises_vad_streaming_boost_and_synchronizes_before_success(self):
        self.assertIs(self.run_warmup(), True)
        self.factory.assert_called_once_with(self.runtime, ('ready',), self.runtime.settings.boost_alpha)
        self.stream.feed.assert_called_once_with(bytes(5120))
        self.stream.decode.assert_called_once_with(('synthetic', 32000))
        self.stream.reset_stream.assert_called_once()
        self.cuda.synchronize.assert_called_once()

    def test_invalid_fixed_bank_fails_before_decode(self):
        for clips in ({}, {'short': b'\0\0'}, {str(i): b'x' for i in range(10)}):
            self.runtime.fixed_clips = clips
            with self.assertRaises(RuntimeError): self.run_warmup()
        self.factory.assert_not_called()

    def test_import_or_gpu_failure_propagates_and_cannot_report_success(self):
        self.stream.decode.side_effect = ImportError('synthetic compiler failure')
        with self.assertRaises(ImportError): self.run_warmup()
        self.cuda.synchronize.assert_not_called()

    def test_noop_decode_is_not_a_warmup_pass(self):
        self.stream.buffer.step = 0
        with self.assertRaises(RuntimeError): self.run_warmup()

    def test_readiness_requires_real_warmup_pass_and_expected_pipeline(self):
        for passed, pipeline, expected in ((False, '1.12.0', 503),
                (True, None, 503), (True, 'other-version', 503), (True, '1.12.0', 200)):
            runtime = MagicMock(warmup_passed=passed, pipecat_version=pipeline)
            with patch('patient_listener.app.server.VoiceRuntime.load', return_value=runtime):
                with TestClient(create_app(Settings(voice_enabled=True))) as client:
                    response = client.get('/healthz')
                    self.assertEqual(response.status_code, expected)
                    self.assertEqual(response.json()['streaming_ready'], expected == 200)
                    self.assertIs(response.json()['production_acceptance_verified'], False)
                runtime.close.assert_called_once()
