"""Bounded on-demand plan building. No scheduling, GPU loading, or paid calls on import."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .llm.validate import check_meaning_hint
from .schemas import Plan, PlanFacts, PlanItem
from .voice.hints import template_hint_lines


class PlanConflict(ValueError):
    pass


def select_words(store, person_id: str, limit: int):
    from .schedule.fsrs import Card, due_tonight
    words = {w.id: w for w in store.words(person_id)}
    # Filter obsolete cards BEFORE applying the bound, so they cannot starve the plan.
    cards = {wid: value for wid, value in store.all_cards(person_id).items() if wid in words}
    for wid in words:
        cards.setdefault(wid, Card.new().to_json())
    due = due_tonight(cards, k=limit)
    if not due:
        previous = [i.word_id for i in store.load_plan(person_id).items if i.word_id in words]
        chosen = previous[:limit] or list(words)[:limit]
    else:
        chosen = due
    return [words[wid] for wid in chosen], set(due)


async def generate_plan(store, person_id: str, *, actor: str, llm, max_words: int = 1,
                        use_ai: bool = False,
                        render: Callable[[str], Awaitable[bytes]] | None = None,
                        tts_model: str = '', voice: str = '', max_model_calls: int | None = None,
                        audio_profile: str = 'legacy') -> dict:
    if not store.can_manage_profile(person_id, actor):
        raise PermissionError('Plan generation requires the linked decision-maker')
    if type(max_words) is not int or not 1 <= max_words <= 10:
        raise ValueError('max_words must be 1..10')
    if max_model_calls is not None and (type(max_model_calls) is not int or max_model_calls < 0):
        raise ValueError('max_model_calls must be a nonnegative integer')
    words, due = select_words(store, person_id, max_words)
    if not words:
        raise ValueError('Approve at least one word before generating a word plan')
    hints, clips = {}, []
    calls = model_hints = 0
    for word in words:
        meaning = None
        if use_ai and store.is_ai_enabled() and (max_model_calls is None or calls < max_model_calls):
            calls += 1  # one attempt per word; no retries
            try:
                candidate = await asyncio.wait_for(llm.plan(PlanFacts(
                    word=word.text, kind=word.kind, meaning_cue=word.meaning_cue,
                    first_letter=word.first_sound or word.text[:1])), timeout=10)
                if (store.is_ai_enabled() and isinstance(candidate, str)
                        and candidate.strip() and check_meaning_hint(candidate, word.text).ok):
                    meaning = candidate
            except Exception:
                pass  # invalid, late or unavailable -> validated template
        lines = template_hint_lines(word, meaning)
        if not check_meaning_hint(lines.meaning, word.text).ok:
            # Cues are user supplied and are not automatically safe meaning hints.
            for neutral in ('Think about it.', 'Can you recall this?', 'What comes to mind?'):
                if check_meaning_hint(neutral, word.text).ok:
                    lines = template_hint_lines(word, neutral)
                    break
            else:
                raise ValueError('No safe meaning hint is available')
            meaning = None
        model_hints += meaning is not None
        hints[word.id] = lines
        if render is not None:
            for level, text in enumerate((lines.meaning, lines.sound, lines.word), 1):
                pcm = await render(text)
                if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
                    raise ValueError('Renderer must return nonempty mono PCM16 audio')
                if len(pcm) > 22050 * 2 * 20:
                    raise ValueError('A generated hint exceeds the 20 second audio limit')
                clips.append((word.id, level, text, tts_model, voice, pcm, audio_profile))
    # If switched off during rendering, never publish model-authored hint content.
    if model_hints and not store.is_ai_enabled():
        raise PlanConflict('AI was disabled during generation; retry with templates')
    plan = Plan(person_id, 'review', tuple(PlanItem(w.id, 'due' if w.id in due else 'returning',
                'Who is this?' if w.kind == 'person' else "What's this?") for w in words),
                store.person_pause(person_id))
    try:
        store.publish_generated_plan(plan, words, hints, clips, actor=actor)
    except ValueError as exc:
        raise PlanConflict(str(exc)) from exc
    return {'person_id': person_id, 'plan_items': len(plan.items), 'model_attempts': calls,
            'model_hints': model_hints, 'template_hints': len(words) - model_hints,
            'rendered_clips': len(clips), 'word_ids': [w.id for w in words]}
