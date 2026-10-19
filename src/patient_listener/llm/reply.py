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
from dataclasses import dataclass
from typing import Optional

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
    llm: Llm, facts: ReplyFacts, timeout_s: float = 1.5, ai_enabled: bool = True
) -> ReplyResult:
    template = templates.reply_template(facts)

    if not ai_enabled:
        return ReplyResult(text=template, used_template=True, reason="ai_disabled")

    # One live attempt with a hard deadline; a stall is worse than a plain line.
    try:
        line = await asyncio.wait_for(llm.reply(facts, timeout_s), timeout=timeout_s)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - any model error -> template
        return ReplyResult(text=template, used_template=True, reason="reply_timeout")

    if line is None:
        return ReplyResult(text=template, used_template=True, reason="no_line")

    verdict = check_reply(line, facts)
    if verdict.ok:
        return ReplyResult(text=line, used_template=False)

    # Retry once, stating the reason (the adapter re-prompts "Do not say X.").
    try:
        retried = await asyncio.wait_for(
            llm.reply(facts, timeout_s), timeout=timeout_s
        )
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        return ReplyResult(text=template, used_template=True, reason=f"{verdict.reason}->timeout")

    if retried is not None and check_reply(retried, facts).ok:
        return ReplyResult(text=retried, used_template=False)

    return ReplyResult(text=template, used_template=True, reason=verdict.reason)
