"""Synthetic live-service acceptance checks. Never writes API keys or model text to reports."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import json
import math
from pathlib import Path
import statistics
import time
from types import SimpleNamespace

from ..config import Settings
from ..llm.reply import produce_reply
from ..llm.token_factory import TokenFactoryLlm
from ..llm.validate import check_meaning_hint, check_reply
from ..schemas import PlanFacts, ReplyFacts
from ..types import HintLevel, Need


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summary(rows):
    timings = [row['elapsed_s'] for row in rows]
    return {
        'runs': len(rows),
        'accepted': sum(row.get('accepted', False) for row in rows),
        'p50_s': round(statistics.median(timings), 3) if timings else None,
        'p95_s': percentile(timings, .95),
        'outcomes': dict(Counter(row['outcome'] for row in rows)),
    }


def reply_facts():
    return ReplyFacts(
        person_first_name='Demo', topic='a walk', hint_level=HintLevel.NONE,
        practice_words=('Biscuit', 'kettle'), found=(),
        last_words_heard='I went for a walk today',
        needs=frozenset({Need.FINDING_WORDS}), allowed_names=frozenset({'Demo'}),
    )


class ObservedClient:
    """Capture only JSON/type flags, never raw content, from an actual SDK response."""
    def __init__(self, inner, observation):
        self.inner = inner
        self.observation = observation
        self.chat = SimpleNamespace(completions=self)

    async def __aenter__(self):
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.inner.__aexit__(*args)

    async def create(self, **kwargs):
        response = await self.inner.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content or ''
        self.observation['nonempty'] = bool(raw.strip())
        self.observation['think_tag'] = '<think' in raw.lower()
        self.observation['finish_reason'] = response.choices[0].finish_reason
        try:
            data = json.loads(raw)
            self.observation['raw_json_object'] = isinstance(data, dict)
            field = 'line' if kwargs['model'] == self.observation['reply_model'] else 'meaning'
            self.observation['expected_field'] = (
                isinstance(data, dict) and isinstance(data.get(field), str)
                and bool(data[field].strip())
            )
        except (ValueError, TypeError):
            self.observation['raw_json_object'] = False
            self.observation['expected_field'] = False
        return response


async def run_checks(settings, runs, pipeline_runs, diagnostic_timeout, *, client_factory=None):
    if client_factory is None:
        from openai import AsyncOpenAI
        client_factory = AsyncOpenAI
    report = {
        'synthetic_inputs_only': True,
        'models': {'lightning': settings.reply_model, 'super': settings.plan_model},
        'response_format': 'json_object',
        'note': 'Measures complete text calls, not first audio or deployed voice latency.',
        'diagnostic': {}, 'pipeline': [],
    }
    facts = reply_facts()
    plan_facts = PlanFacts(word='kettle', kind='object',
                           meaning_cue='you boil water in it', first_letter='K')
    for name in ('lightning', 'super'):
        rows = []
        for index in range(runs):
            observed = {'reply_model': settings.reply_model}
            def factory(**kwargs):
                return ObservedClient(client_factory(**kwargs), observed)
            model = TokenFactoryLlm(settings, client_factory=factory)
            started = time.perf_counter()
            row = {'run': index + 1, 'accepted': False}
            try:
                if name == 'lightning':
                    line = await model.reply(facts, diagnostic_timeout)
                    verdict = check_reply(line, facts) if line else None
                else:
                    line = await asyncio.wait_for(model.plan(plan_facts), diagnostic_timeout)
                    verdict = check_meaning_hint(line, plan_facts.word) if line else None
                row['accepted'] = bool(verdict and verdict.ok)
                row['outcome'] = 'accepted' if row['accepted'] else (verdict.reason if verdict else 'empty')
            except Exception as exc:
                row['outcome'] = type(exc).__name__
            row['elapsed_s'] = round(time.perf_counter() - started, 3)
            row.update({k: v for k, v in observed.items() if k != 'reply_model'})
            rows.append(row)
            print(f"{name} {index+1}/{runs}: {row['outcome']} ({row['elapsed_s']}s)", flush=True)
        report['diagnostic'][name] = {'summary': summary(rows), 'results': rows}
    model = TokenFactoryLlm(settings, client_factory=client_factory)
    for index in range(pipeline_runs):
        started = time.perf_counter()
        result = await produce_reply(model, facts, timeout_s=settings.live_reply_timeout_s)
        row = {
            'run': index + 1, 'elapsed_s': round(time.perf_counter()-started, 3),
            'accepted': not result.used_template,
            'outcome': result.reason if result.used_template else 'model_reply',
            'used_template': result.used_template,
            'delivered_line_valid': check_reply(result.text, facts).ok,
        }
        report['pipeline'].append(row)
        print(f"pipeline {index+1}/{pipeline_runs}: {row['outcome']} ({row['elapsed_s']}s)", flush=True)
    report['pipeline_summary'] = summary(report['pipeline'])
    report['g03_raw_json_20_each'] = all(
        len(group['results']) >= 20 and all(
            r.get('raw_json_object') and r.get('nonempty') and r.get('expected_field')
            and not r.get('think_tag') and r.get('finish_reason') == 'stop'
            for r in group['results']
        ) for group in report['diagnostic'].values()
    )
    report['all_pipeline_outputs_valid'] = bool(report['pipeline']) and all(
        r['delivered_line_valid'] for r in report['pipeline']
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=20, help='Calls per model; 20 required for G-03 evidence')
    parser.add_argument('--pipeline-runs', type=int, default=5)
    parser.add_argument('--diagnostic-timeout', type=float, default=20)
    parser.add_argument('--output', type=Path, default=Path('token-factory-check.json'))
    args = parser.parse_args()
    if not 1 <= args.runs <= 20 or not 1 <= args.pipeline_runs <= 20 or args.diagnostic_timeout <= 0:
        parser.error('runs must be 1..20 and timeout positive')
    settings = Settings()
    key = settings.nebius_api_key.strip()
    if not key or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
        parser.error('Set a valid NEBIUS_API_KEY in this terminal; key is never printed')
    settings = replace(settings, nebius_api_key=key)
    print(f'Synthetic test: {args.runs} calls per model plus {args.pipeline_runs} pipeline runs (which may retry once).')
    print('Super adapter retains its 10-second internal limit; diagnostic timeout does not change app budgets.')
    report = asyncio.run(run_checks(settings, args.runs, args.pipeline_runs, args.diagnostic_timeout))
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('G-03 raw JSON evidence:', report['g03_raw_json_20_each'])
    print('Pipeline:', report['pipeline_summary'])
    print('Report:', args.output)


if __name__ == '__main__':
    main()
