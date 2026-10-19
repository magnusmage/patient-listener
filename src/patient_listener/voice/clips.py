"""Cached audio clips and the TTS port.

Latency levers 1-2 (workbook: Tech stack): hints are pre-written overnight and clips are
pre-rendered, so the live path plays cached audio and runs no model for them. In this offline
sandbox the "audio" is placeholder bytes; on the GPU box :class:`MagpieTts` synthesises real
22.05 kHz audio with ``nemo_toolkit[tts]`` and normalises each clip to -20 LUFS. The clip
*keys* and the cache contract are identical in both.
"""

from __future__ import annotations

from typing import Iterable, Optional

__all__ = ["ClipCache", "StubTts", "GENERIC_CLIP_KEYS"]

GENERIC_CLIP_KEYS = ("mm", "offer_hint", "yes", "take_your_time", "no_rush", "a_bit_stronger")


class ClipCache:
    """In-memory clip cache keyed by clip id ('mm', 'hint:<word>:<lvl>', ...)."""

    def __init__(self) -> None:
        self._clips: dict[str, bytes] = {}

    def warm(self, person_id: str, hint_keys: Iterable[str] = ()) -> int:
        """Pre-render the generic clips and this person's hint clips. Returns the count."""
        keys = list(GENERIC_CLIP_KEYS) + list(hint_keys)
        for k in keys:
            self._clips.setdefault(k, f"<audio:{k}>".encode())
        return len(self._clips)

    def clip(self, key: str) -> Optional[bytes]:
        return self._clips.get(key)

    def has(self, key: str) -> bool:
        return key in self._clips


class StubTts:
    """Offline TTS: returns placeholder bytes. Implements the ``Tts`` port."""

    def __init__(self, cache: Optional[ClipCache] = None) -> None:
        self.cache = cache or ClipCache()

    async def speak(self, text: str, voice: str) -> Iterable[bytes]:
        # Real adapter splits into sentences (<=20 s/utterance, #15300) and streams 22.05 kHz.
        return [f"<tts:{voice}:{text}>".encode()]

    def clip(self, key: str) -> Optional[bytes]:
        return self.cache.clip(key)
