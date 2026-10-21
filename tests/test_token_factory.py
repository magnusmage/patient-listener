"""Token Factory integration checks using an in-memory client, never a live API key."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from patient_listener.config import Settings
from patient_listener.llm.factory import build_llm
from patient_listener.llm.reply import TemplateLlm, produce_reply
from patient_listener.llm.token_factory import TokenFactoryLlm
from tests.test_faults import _facts


class Client:
    def __init__(self, content, delay=0):
        self.content = content
        self.delay = delay
        self.calls = []
        self.chat = SimpleNamespace(completions=self)
        self.closed = False

    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closed = True

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(self.delay)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class TokenFactoryTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, content, cap=60, delay=0):
        client = Client(content, delay)
        model = TokenFactoryLlm(
            Settings(nebius_api_key='test-only', max_lightning_calls_per_session=cap),
            client_factory=lambda **kwargs: client,
        )
        return model, client

    async def test_reply_uses_configured_model_and_disables_thinking(self):
        model, client = self.adapter('{"line":"Tell me more."}')
        result = await produce_reply(model, _facts())
        self.assertFalse(result.used_template)
        self.assertEqual(client.calls[0]['model'], model.settings.reply_model)
        self.assertEqual(client.calls[0]['max_tokens'], 60)
        self.assertFalse(client.calls[0]['extra_body']['chat_template_kwargs']['enable_thinking'])
        self.assertTrue(client.closed)

    async def test_invalid_json_and_revealed_word_fall_back(self):
        for content in ('not json', '[]', '{"line":"Is that Biscuit the puppy?"}'):
            model, _ = self.adapter(content)
            self.assertTrue((await produce_reply(model, _facts())).used_template)

    async def test_timeout_closes_client_and_falls_back(self):
        model, client = self.adapter('{}', delay=1)
        self.assertTrue((await produce_reply(model, _facts(), timeout_s=0.01)).used_template)
        self.assertTrue(client.closed)

    async def test_completeness_requires_boolean_true_and_shares_call_cap(self):
        model, client = self.adapter('{"complete":"false"}', cap=1)
        self.assertFalse(await model.is_complete('Question', 'Answer', 0.1))
        self.assertIsNone(await model.reply(_facts(), 0.1))
        self.assertEqual(len(client.calls), 1)

    async def test_kill_switch_makes_no_request(self):
        model, client = self.adapter('{}')
        self.assertTrue((await produce_reply(model, _facts(), ai_enabled=False)).used_template)
        self.assertEqual(client.calls, [])

    def test_factory_defaults_to_templates_and_respects_disabled_ai(self):
        self.assertIsInstance(build_llm(Settings(nebius_api_key='')), TemplateLlm)
        self.assertIsInstance(build_llm(Settings(nebius_api_key='test', ai_enabled=False)), TemplateLlm)

    def test_factory_selects_session_local_token_factory_when_available(self):
        with patch.dict('sys.modules', {'openai': SimpleNamespace()}):
            cfg = Settings(nebius_api_key='test', ai_enabled=True)
            self.assertIsInstance(build_llm(cfg), TokenFactoryLlm)
            self.assertIsNot(build_llm(cfg), build_llm(cfg))
