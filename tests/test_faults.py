"""Faults and fallbacks (F-set, FR-24, FR-84). Every fault yields a sensible line; nothing is
logged wrongly. The reply orchestration is async, driven here with ``asyncio.run``."""

from __future__ import annotations

import asyncio
import unittest
from typing import Optional

from patient_listener.llm.reply import produce_reply
from patient_listener.ports import Llm
from patient_listener.schemas import PlanFacts, ReplyFacts
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_margaret
from patient_listener.types import HintLevel, Need


def _facts(**kw) -> ReplyFacts:
    base = dict(
        person_first_name="Margaret",
        topic="photo",
        hint_level=HintLevel.NONE,
        practice_words=("Leo", "Biscuit", "kettle"),
        found=(),
        last_words_heard="",
        needs=frozenset({Need.FINDING_WORDS}),
        allowed_names=frozenset({"Margaret", "Leo", "Biscuit", "kettle"}),
    )
    base.update(kw)
    return ReplyFacts(**base)


class RevealingLlm(Llm):
    """Always returns a line that reveals a not-yet-found word (scenario 6)."""

    async def reply(self, facts, timeout_s): return "Is that Biscuit the puppy?"
    async def plan(self, facts): return None
    async def is_complete(self, q, t, timeout_s): return True


class SlowLlm(Llm):
    async def reply(self, facts, timeout_s):
        await asyncio.sleep(timeout_s + 1.0)  # exceeds the budget
        return "too late"
    async def plan(self, facts): return None
    async def is_complete(self, q, t, timeout_s): return True


class GoodLlm(Llm):
    async def reply(self, facts, timeout_s): return "Lovely. Tell me more."
    async def plan(self, facts): return "You boil water in it."
    async def is_complete(self, q, t, timeout_s): return True


class TestReplyOrchestration(unittest.TestCase):
    def test_reveal_falls_back_to_template(self):
        # Scenario 6: reject -> retry -> reject -> template; never reaches the person.
        r = asyncio.run(produce_reply(RevealingLlm(), _facts(), timeout_s=0.2))
        self.assertTrue(r.used_template)
        self.assertEqual(r.reason, "reveals_word")
        self.assertNotIn("Biscuit", r.text)

    def test_timeout_falls_back_to_template(self):
        r = asyncio.run(produce_reply(SlowLlm(), _facts(), timeout_s=0.05))
        self.assertTrue(r.used_template)
        self.assertEqual(r.reason, "reply_timeout")

    def test_good_line_used(self):
        r = asyncio.run(produce_reply(GoodLlm(), _facts(), timeout_s=0.2))
        self.assertFalse(r.used_template)
        self.assertEqual(r.text, "Lovely. Tell me more.")

    def test_kill_switch_forces_template(self):
        # FR-84: AI off -> template, even with a working model available.
        r = asyncio.run(produce_reply(GoodLlm(), _facts(), timeout_s=0.2, ai_enabled=False))
        self.assertTrue(r.used_template)
        self.assertEqual(r.reason, "ai_disabled")


class TestPlanMissing(unittest.TestCase):
    def test_default_plan_from_approved_words(self):
        # plan_missing: nightly didn't run -> a default plan from approved words, not an error.
        store = SqliteStore()
        pid = seed_margaret(store)
        plan = store.load_plan(pid)  # no plan row exists yet
        self.assertGreater(len(plan.items), 0)
        self.assertLessEqual(len(plan.items), 10)


if __name__ == "__main__":
    unittest.main()
