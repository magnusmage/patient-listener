"""Validated per-person overrides after merging need profiles. No I/O or model calls."""
from dataclasses import replace
import math

from .types import HintLevel, Need
from .voice.merge import merge

WAIT_FIELDS = {'backchannel_s', 'offer_hint_s', 'max_wait_s', 'max_session_min'}
PROFILE_FIELDS = WAIT_FIELDS | {'needs', 'hint_order'}
NEED_KEYS = {n.value for n in Need if n != Need.LISTENING}
_HINTS = {'meaning': HintLevel.MEANING, 'sound': HintLevel.SOUND, 'word': HintLevel.WORD}


def normalize_changes(changes: dict, *, patient: bool = False) -> dict:
    allowed = WAIT_FIELDS if patient else PROFILE_FIELDS
    if not isinstance(changes, dict) or not changes or set(changes) - allowed:
        raise ValueError('Unsupported or empty settings change')
    clean = dict(changes)
    if 'needs' in clean:
        needs = clean['needs']
        if (not isinstance(needs, list) or not needs or
                any(not isinstance(n, str) or n not in NEED_KEYS for n in needs) or
                len(set(needs)) != len(needs)):
            raise ValueError('Choose one or more distinct supported needs')
        clean['needs'] = sorted(needs)
    if 'hint_order' in clean:
        order = clean['hint_order']
        if (not isinstance(order, list) or len(order) != 3 or
                any(not isinstance(h, str) or h not in _HINTS for h in order) or
                len(set(order)) != 3 or order[-1] != 'word'):
            raise ValueError('Hint order must be meaning/sound or sound/meaning, then word')
    for name in WAIT_FIELDS & clean.keys():
        value = clean[name]
        if value is None:
            continue
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError('Waits must be finite numbers or null')
        if name == 'max_session_min' and type(value) is not int:
            raise ValueError('Session minutes must be an integer or null')
    return clean


def resolve_profile(needs: frozenset[Need], overrides: dict):
    cfg = merge(needs)
    values = {k: v for k, v in overrides.items() if k in WAIT_FIELDS}
    if Need.WORDS_OUT in needs:
        if any(values.get(k) is not None for k in ('backchannel_s', 'offer_hint_s')):
            raise ValueError('Getting words out must keep listening sounds and hint offers off')
    if 'hint_order' in overrides:
        values['hint_order'] = tuple(_HINTS[h] for h in overrides['hint_order'])
    return replace(cfg, **values)


def extend_only(cfg, changes: dict) -> dict:
    clean = normalize_changes(changes, patient=True)
    for name, value in clean.items():
        current = getattr(cfg, name)
        if value is not None and (current is None or value < current):
            raise PermissionError('You may lengthen or switch off a wait or session cap')
    resolve_profile(cfg.needs, {**profile_values(cfg), **clean})
    return clean


def profile_values(cfg) -> dict:
    return {**{name: getattr(cfg, name) for name in WAIT_FIELDS},
            'needs': sorted(n.value for n in cfg.needs),
            'hint_order': [level.name.lower() for level in cfg.hint_order]}
