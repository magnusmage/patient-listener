"""Validate the live-check report without external services or credentials."""
import contextlib
import io
import json
from types import SimpleNamespace
import unittest
from patient_listener.config import Settings
from patient_listener.tools.token_factory_check import run_checks


class FakeClient:
    def __init__(self, content=None, **kwargs):
        self.content = content
        self.chat = SimpleNamespace(completions=self)
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def create(self, **kwargs):
        content = self.content or (
            '{"meaning":"You boil water in it."}' if 'super' in kwargs['model']
            else '{"line":"Tell me more."}'
        )
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason='stop')])


class CheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_gate_and_report_privacy(self):
        cfg = Settings(nebius_api_key='secret-never-save')
        with contextlib.redirect_stdout(io.StringIO()):
            report = await run_checks(cfg, 20, 2, 20, client_factory=FakeClient)
        self.assertTrue(report['g03_raw_json_20_each'])
        self.assertTrue(report['all_pipeline_outputs_valid'])
        self.assertEqual(report['pipeline_summary']['accepted'], 2)
        encoded = json.dumps(report)
        self.assertNotIn('secret-never-save', encoded)
        self.assertNotIn('Tell me more.', encoded)
        self.assertNotIn('You boil water in it.', encoded)

    async def test_thinking_or_invalid_json_cannot_pass_gate(self):
        for content in ('<think>private</think>{"line":"Tell me more."}', 'not json'):
            with contextlib.redirect_stdout(io.StringIO()):
                report = await run_checks(Settings(), 1, 1, 20,
                    client_factory=lambda **kw: FakeClient(content, **kw))
            self.assertFalse(report['g03_raw_json_20_each'])
            self.assertTrue(report['all_pipeline_outputs_valid'])

    async def test_service_errors_are_sanitized_and_pipeline_falls_back(self):
        def broken(**kwargs): raise RuntimeError('sensitive-provider-error')
        with contextlib.redirect_stdout(io.StringIO()):
            report = await run_checks(Settings(), 1, 1, 20, client_factory=broken)
        self.assertFalse(report['g03_raw_json_20_each'])
        self.assertTrue(report['all_pipeline_outputs_valid'])
        self.assertTrue(report['pipeline'][0]['used_template'])
        self.assertNotIn('sensitive-provider-error', json.dumps(report))
