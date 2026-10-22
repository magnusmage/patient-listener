"""Select a session-local LLM, with the persisted switch read on every call."""
from ..config import Settings
from .reply import TemplateLlm
from .token_factory import TokenFactoryLlm


class PolicyLlm:
    def __init__(self, model, store):
        self.model, self.store = model, store

    async def _call(self, method, fallback, *args):
        if not self.store.is_ai_enabled():
            return fallback
        result = await getattr(self.model, method)(*args)
        return result if self.store.is_ai_enabled() else fallback

    async def reply(self, facts, timeout_s):
        return await self._call('reply', None, facts, timeout_s)

    async def plan(self, facts):
        return await self._call('plan', None, facts)

    async def is_complete(self, question, transcript, timeout_s):
        return await self._call('is_complete', False, question, transcript, timeout_s)


def build_llm(settings: Settings, store=None):
    # With a store, environment AI_ENABLED sets only the initial DB value. Keep the
    # configured adapter available so off -> on works without rebuilding the session.
    model = TemplateLlm()
    if settings.nebius_api_key.strip() and (store is not None or settings.ai_enabled):
        try:
            import openai  # optional llm extra
        except ImportError:
            pass
        else:
            model = TokenFactoryLlm(settings)
    return PolicyLlm(model, store) if store is not None else model
