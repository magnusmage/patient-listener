"""Select a session-local LLM; local development defaults to templates."""
from ..config import Settings
from .reply import TemplateLlm
from .token_factory import TokenFactoryLlm


def build_llm(settings: Settings):
    if not settings.ai_enabled or not settings.nebius_api_key.strip():
        return TemplateLlm()
    try:
        import openai  # optional llm extra
    except ImportError:
        return TemplateLlm()
    return TokenFactoryLlm(settings)
