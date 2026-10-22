"""The real Token Factory adapter (D-05, D-06). Requires network access and ``NEBIUS_API_KEY``,
so it is NOT exercised in the offline sandbox - the tests inject :class:`TemplateLlm` instead.
On the GPU/deploy box, construct ``TokenFactoryLlm`` and pass it wherever an ``Llm`` is needed;
nothing else changes (ports and adapters).

Key production rules baked in here:

* ``enable_thinking: false`` on every JSON call (issue #28 / G-03), via
  ``extra_body={"chat_template_kwargs": {"enable_thinking": False}}``.
* ``max_tokens=60`` and one sentence for live replies (D-05).
* ``response_format`` JSON schema; strip any ``<think>`` text before the validator (#19229).
* 1.5 s budget for replies, 1.0 s for the completeness check; both fall back in the caller.

This module imports ``openai`` lazily so the package imports cleanly without it installed.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

from ..config import Settings, settings as default_settings
from ..ports import Llm
from ..schemas import PlanFacts, ReplyFacts

__all__ = ["TokenFactoryLlm"]

_THINK = re.compile(r"<think>.*?</think>", re.S)

_REPLY_SYSTEM = (
    "You are a patient practice partner for an adult who is practising talking. "
    "You only write ONE short spoken line. At most 15 words. One idea. Plain words. "
    "No lists, no emoji. Never say a practice word that is not in \"found\" unless hint_level "
    "is 3. Never correct grammar. Never say \"wrong\" or \"no\". No medical advice, medication, "
    "diagnosis or prognosis; if asked, say \"That's one for your doctor or therapist.\" "
    "If rejection_reason is provided, correct that validation failure. "
    "Follow the profile rules exactly. You are an AI. Return JSON: {\"line\": \"...\"}."
)

_MEANING_SYSTEM = (
    "Write one meaning hint for one practice word, for an adult who is practising talking. "
    "Use only the facts given. JSON schema: {\"meaning\": str}. meaning: <= 12 words, describes "
    "it using the meaning cue; must NOT contain the word, any part of it, or a word starting "
    "with the same first two letters."
)

_COMPLETE_SYSTEM = (
    "You see a partial transcript of someone answering a question. Answer only JSON "
    "{\"complete\": true|false}. true only if the answer reads as a finished thought. "
    "Repetitions like \"my my my\" or a cut-off word mean false."
)


def _strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


class TokenFactoryLlm(Llm):
    def __init__(self, settings: Settings | None = None, *, client_factory=None) -> None:
        self.settings = settings or default_settings
        self._client_factory = client_factory
        self._reply_model = self.settings.reply_model
        self._plan_model = self.settings.plan_model
        self._calls = 0

    async def _json_call(self, model: str, system: str, user: str, max_tokens: int,
                         timeout_s: float) -> dict:
        factory = self._client_factory
        if factory is None:
            from openai import AsyncOpenAI
            factory = AsyncOpenAI
        # SessionEngine uses a fresh event loop per call. Scope the HTTP client to that loop.
        async with factory(base_url=self.settings.token_factory_base_url,
                           api_key=self.settings.nebius_api_key,
                           max_retries=0, timeout=timeout_s) as client:
            resp = await asyncio.wait_for(client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            ), timeout=timeout_s)
        content = _strip_think(resp.choices[0].message.content or "{}")
        data = json.loads(content or "{}")
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data

    def _claim_call(self) -> bool:
        if self._calls >= self.settings.max_lightning_calls_per_session:
            return False
        self._calls += 1
        return True

    async def reply(self, facts: ReplyFacts, timeout_s: float) -> Optional[str]:
        if not self._claim_call():
            return None  # LLM10: cap calls per session, then templates only
        user = json.dumps(
            {
                "person_first_name": facts.person_first_name,
                "topic": facts.topic,
                "last_words_heard": facts.last_words_heard,
                "hint_level": int(facts.hint_level),
                "found": list(facts.found),
                "practice_words": list(facts.practice_words),
                "needs": sorted(n.value for n in facts.needs),
                "banned_phrases": sorted(facts.banned_phrases),
                "rejection_reason": facts.rejection_reason,
            }
        )
        data = await self._json_call(self._reply_model, _REPLY_SYSTEM, user, max_tokens=60, timeout_s=timeout_s)
        line = data.get("line")
        return line if isinstance(line, str) and line.strip() else None

    async def plan(self, facts: PlanFacts) -> Optional[str]:
        user = json.dumps(
            {
                "word": facts.word,
                "kind": facts.kind,
                "meaning_cue": facts.meaning_cue,
                "first_letter": facts.first_letter,
            }
        )
        data = await self._json_call(self._plan_model, _MEANING_SYSTEM, user, max_tokens=60, timeout_s=10.0)
        meaning = data.get("meaning")
        return meaning if isinstance(meaning, str) and meaning.strip() else None

    async def is_complete(self, question: str, transcript: str, timeout_s: float) -> bool:
        if not self._claim_call():
            return False
        user = f'question: "{question}"\ntranscript: "{transcript}"'
        data = await self._json_call(self._reply_model, _COMPLETE_SYSTEM, user, max_tokens=20, timeout_s=timeout_s)
        return data.get("complete") is True
