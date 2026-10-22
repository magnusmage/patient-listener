"""Live reply orchestration (workbook: AI and safety -> Self-correction; FR-24).

``produce_reply`` is the single place the live model is called:

1. read the kill switch (FR-84); if AI is off, use a template;
2. call the model with a 1.5 s budget; on timeout, template at once (no retry);
3. validate the line; on reject, retry once with the reason stated; on a second reject,
   template.

:class:`TemplateLlm` is the offline / kill-switch implementation of the ``Llm`` port: its
``reply`` returns ``None`` so the orchestration always falls back to a validated template,
which is exactly the behaviour FR-84 requires and which runs with no GPU or network. The GPU
box injects :class:`~patient_listener.llm.token_factory.TokenFactoryLlm` instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Callable, Optional

from ..ports import Llm
from ..schemas import PlanFacts, ReplyFacts
from . import templates
from .validate import Verdict, check_reply

__all__ = ["TemplateLlm", "produce_reply", "ReplyResult"]


@dataclass(frozen=True)
class ReplyResult:
    text: str
    used_template: bool
    reason: str = ""  # why the template was used, if it was


class TemplateLlm(Llm):
    """Offline LLM: never returns a model line, so templates are always used (FR-84 mode)."""

    async def reply(self, facts: ReplyFacts, timeout_s: float) -> Optional[str]:
        return None

    async def plan(self, facts: PlanFacts) -> Optional[str]:
        return None  # nightly falls back to the meaning cue / template

    async def is_complete(self, question: str, transcript: str, timeout_s: float) -> bool:
        """Heuristic stand-in for Lightning's yes/no (Getting words out). Repetitions like
        'my my my' or an empty/one-word transcript read as not complete."""
        toks = transcript.split()
        if len(toks) < 2:
            return False
        if len(toks) >= 2 and toks[-1].lower() == toks[-2].lower():
            return False
        if transcript.rstrip().endswith(("-", "\u2026", "...")):
            return False
        return True


async def produce_reply(
    llm: Llm, facts: ReplyFacts, timeout_s: float = 1.5,
    ai_enabled: bool | Callable[[], bool] = True,
) -> ReplyResult:
    template = templates.reply_template(facts)
    enabled = ai_enabled if callable(ai_enabled) else lambda: ai_enabled
    deadline = asyncio.get_running_loop().time() + timeout_s
    reason = "reply_timeout"
    request_facts = facts
    for attempt in range(2):
        # Re-read before each attempt; switching off must prevent the retry too.
        if not enabled():
            return ReplyResult(template, True, "ai_disabled")
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return ReplyResult(template, True, reason)
        try:
            line = await asyncio.wait_for(llm.reply(request_facts, remaining), remaining)
        except Exception:
            return ReplyResult(template, True, reason)
        if not enabled():
            return ReplyResult(template, True, "ai_disabled")
        if line is None:
            return ReplyResult(template, True, "no_line" if not attempt else reason)
        verdict = check_reply(line, facts)
        if verdict.ok:
            return ReplyResult(line, False)
        reason = verdict.reason if attempt else f"{verdict.reason}->timeout"
        request_facts = replace(facts, rejection_reason=verdict.reason)
    return ReplyResult(template, True, verdict.reason)
