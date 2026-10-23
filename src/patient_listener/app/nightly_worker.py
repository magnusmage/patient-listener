"""Single-worker development scheduler; uses local-day ledger to avoid repeating paid work.

Production still requires the workbook's durable job/deployment stack. This worker
runs only while the API server is alive; a late start catches up today's run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from types import SimpleNamespace
from ..schedule.timezones import schedule_timezone

from fastapi import HTTPException
from .console_auth import ConsoleAccess
from .plan_jobs import PlanBusy, run_generation

_LOG = logging.getLogger('uvicorn.error.patient_listener.nightly')


class NightlyWorker:
    def __init__(self, app):
        self.app = app
        self.cfg = app.state.settings
        self._busy_logged = set()

    async def run_due(self, now: datetime | None = None) -> list[dict]:
        if not self.cfg.nightly_enabled:
            return []
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('Nightly clock must be timezone aware')
        local = now.astimezone(schedule_timezone(self.cfg.nightly_timezone))
        if local.strftime('%H:%M') < self.cfg.nightly_time:
            return []
        day = local.date().isoformat()
        state = self.app.state.pl
        store = state.store
        actor = self.cfg.nightly_actor_id
        identity = store.console_identity(actor)
        outcomes = []
        seen = set()
        for name in self.cfg.nightly_people:
            pid = state.people.get(name, name)
            if not store.person_exists(pid):
                continue  # Deleted people must not acquire new ledger rows.
            if pid in seen:
                continue
            seen.add(pid)
            if any(r['local_day'] == day for r in store.nightly_runs(pid)):
                continue  # includes failed and interrupted/running rows: no paid retry
            use_ai = (self.cfg.nightly_use_ai and store.is_ai_enabled()
                      and store.nightly_reserved_calls(day) < self.cfg.nightly_max_model_calls)
            options = SimpleNamespace(max_words=self.cfg.nightly_max_words, use_ai=use_ai,
                                      render_audio=self.cfg.nightly_render_audio)
            claimed = False

            def admit():
                nonlocal claimed
                budget = store.claim_nightly(day, pid, actor,
                    self.cfg.nightly_max_words if use_ai else 0,
                    self.cfg.nightly_max_model_calls)
                if budget is None:
                    return None
                claimed = True
                return {'max_model_calls': budget}

            def record(status, summary):
                nonlocal claimed
                if not claimed:
                    claimed = store.claim_nightly(day, pid, actor, 0,
                        self.cfg.nightly_max_model_calls) is not None
                if not claimed:
                    return
                store.finish_nightly(day, pid, status, summary)
                _LOG.info('Nightly plan finished person_id=%s local_day=%s status=%s', pid, day, status)
                outcomes.append({'person_id': pid, 'status': status, **summary})

            try:
                if identity is None or not store.can_manage_profile(pid, actor):
                    record('failed', {'reason': 'helper_not_authorized'})
                    continue
                if not store.words(pid):
                    record('skipped', {'reason': 'no_approved_words'})
                    continue
                access = ConsoleAccess(identity['id'], identity['display_name'],
                                       identity['role'], store)
                result = await run_generation(self.app, access, pid, options, on_admitted=admit)
                if not result.get('already_claimed'):
                    record('succeeded', result)
                    self._busy_logged.discard((day, pid))
            except PlanBusy:
                if (day, pid) not in self._busy_logged:
                    _LOG.info('Nightly plan waiting person_id=%s reason=active_session_or_gpu', pid)
                    self._busy_logged.add((day, pid))
                # No ledger claim and no model calls; retry on the next poll today.
            except asyncio.CancelledError:
                # Preserve running status: a provider may have charged for an in-flight call.
                raise
            except HTTPException as exc:
                record('failed', {'reason': 'generation_http_' + str(exc.status_code)})
            except Exception as exc:
                # Never log exception text, which could include a provider request payload.
                record('failed', {'reason': type(exc).__name__})
        return outcomes

    async def run(self):
        _LOG.info('Nightly scheduler enabled time=%s timezone=%s max_words=%d daily_model_limit=%d use_ai=%s',
                  self.cfg.nightly_time, self.cfg.nightly_timezone,
                  self.cfg.nightly_max_words, self.cfg.nightly_max_model_calls, self.cfg.nightly_use_ai)
        while True:
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOG.error('Nightly scheduler check failed error_type=%s', type(exc).__name__)
            await asyncio.sleep(30)
