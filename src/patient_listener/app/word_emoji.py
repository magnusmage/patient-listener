"""Offline visual suggestions from English emoji names and common word aliases."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import emoji

KIND_EMOJI = {
    "person": "👤", "place": "📍", "food": "🍽️",
    "object": "🧺", "activity": "🎯", "phrase": "💬",
}

# Everyday British terms and approximate visuals absent from the Unicode names.
_ALIASES = {
    "biscuit": "🍪", "biscuits": "🍪", "kettle": "♨️",
    "tea": "☕", "cup of tea": "☕", "coffee": "☕",
    "porridge": "🥣", "sofa": "🛋️", "television": "📺",
    "tv": "📺", "mobile phone": "📱", "phone": "📱",
    "garden": "🌳", "seaside": "🏖️", "puppy": "🐶",
    "kitten": "🐱", "doctor": "🧑‍⚕️", "nurse": "🧑‍⚕️",
}
_PERSON_ROLES = frozenset({"doctor", "nurse", "teacher", "farmer", "firefighter", "astronaut"})


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    names: dict[str, str] = {}
    for symbol, data in emoji.EMOJI_DATA.items():
        # Fully qualified glyphs avoid duplicate text/emoji presentation variants.
        if data.get("status") != 2:
            continue
        for name in (data.get("en", ""), *data.get("alias", ())):
            key = _normalize(name)
            if key:
                names.setdefault(key, symbol)
    names.update(_ALIASES)
    return names


def word_emoji(text: str, kind: str) -> str:
    """Prefer a whole-name match, then a phrase component, else a category fallback.

    Suggestions are approximate, not semantic understanding. Never fuzzy-match names
    or spelling: e.g. Leo must not become a zodiac sign or a similar-looking noun.
    """
    key = _normalize(text)
    fallback = KIND_EMOJI.get(kind, "🖼️")
    if not key or (kind == "person" and key not in _PERSON_ROLES):
        return fallback
    names = _names()
    if key in names:
        return names[key]
    words = key.split()
    # Longest contiguous name first; no substring matches inside unknown words.
    for size in range(len(words), 0, -1):
        for start in range(len(words) - size + 1):
            part = " ".join(words[start:start + size])
            if part in names:
                return names[part]
            if size == 1 and len(part) > 3 and part.endswith("s") and not part.endswith("ss"):
                if part[:-1] in names:
                    return names[part[:-1]]
    return fallback
