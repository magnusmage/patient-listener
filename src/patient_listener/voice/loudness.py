"""Being heard: loudness feedback relative to the person's own baseline (FR-13).

This is a feedback bar for the current session, not a measurement of speech or of any
condition. Only relative dB is used, never an absolute number, and no dB value is ever shown
or spoken (DS-P02, the validator bans dB numbers in speech). Production reads RMS dBFS over
voiced frames with ``numpy``; the pure logic here is identical and dependency-free except for
the RMS helper, which uses ``numpy`` where present and a stdlib fallback otherwise.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

__all__ = ["utterance_db", "baseline_db", "loudness_feedback", "LOUDNESS_FLOOR_DB"]

LOUDNESS_FLOOR_DB = -2.0  # FR-13: "a bit stronger?" when >= 2 dB below baseline


def utterance_db(samples: Sequence[float]) -> float:
    """RMS level in dBFS over voiced frames only."""
    if len(samples) == 0:
        return -120.0
    try:
        import numpy as np  # production dependency

        arr = np.asarray(samples, dtype="float64")
        rms = float(np.sqrt(np.mean(np.square(arr)))) + 1e-9
    except Exception:  # pragma: no cover - stdlib fallback
        mean_sq = sum(x * x for x in samples) / len(samples)
        rms = math.sqrt(mean_sq) + 1e-9
    return 20.0 * math.log10(rms)


def baseline_db(phrase_levels: Sequence[float]) -> float:
    """Median dBFS of the 5 phrases read 'in your strong voice' at session start."""
    vals = sorted(phrase_levels)
    n = len(vals)
    if n == 0:
        return -120.0
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def loudness_feedback(
    db: float, baseline: float, floor: float = LOUDNESS_FLOOR_DB
) -> Optional[str]:
    """Return the feedback key when the utterance is >= 2 dB below baseline, else ``None``.

    Shown as a bar and the words 'A bit stronger?' - never a dB number.
    """
    return "a_bit_stronger" if (db - baseline) <= floor else None


class VoicedLevel:
    """Bounded-memory RMS accumulator; callers supply only VAD-positive samples."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.square_sum = 0.0
        self.count = 0

    def add(self, samples):
        for sample in samples:
            value = float(sample)
            if not math.isfinite(value) or abs(value) > 1:
                raise ValueError('Expected finite normalized audio samples')
            self.square_sum += value * value
            self.count += 1

    def level(self):
        if self.count < 1600 or self.square_sum <= 0:
            return None
        return round(20 * math.log10(math.sqrt(self.square_sum / self.count) + 1e-9), 8)


CALIBRATION_PHRASES = (
    'Good morning.', 'How are you today?', 'Please open the window.',
    'I would like some water.', 'Thank you very much.',
)


class SessionLoudness:
    """Five user-confirmed phrases; no levels or samples are persisted."""
    def __init__(self):
        self.phrases = []
        self.baseline = None
        self.pending_power = 0.0
        self.pending_count = 0

    def observe(self, level, count):
        if (not isinstance(level, (int, float)) or not math.isfinite(level)
                or not -120 <= level <= 1 or type(count) is not int or count < 1600):
            return False
        self.pending_power += 10 ** (level / 10) * count
        self.pending_count += count
        return True

    def accept_phrase(self):
        if self.baseline is not None or not self.pending_count:
            return False
        self.phrases.append(10 * math.log10(self.pending_power / self.pending_count))
        self.pending_power = 0.0
        self.pending_count = 0
        if len(self.phrases) == 5:
            self.baseline = baseline_db(self.phrases)
        return True

    def feedback(self, level):
        if self.baseline is None:
            return None
        strong = loudness_feedback(round(level - self.baseline, 6), 0.0) is None
        # Unitless bar position only; neither absolute nor relative dB leaves the server.
        position = max(0.0, min(1.0, 0.6 + (level - self.baseline) / 20))
        return {'type': 'loudness', 'strong': strong, 'position': round(position, 3)}
