"""Fuzzy string similarity.

Production uses ``rapidfuzz`` (D-16, pinned ``rapidfuzz~=3.14``). ``rapidfuzz.fuzz.ratio``
returns ``100 * 2*M / (len1 + len2)`` where ``M`` is the number of matching characters
(the indel/LCS ratio). The standard library's :class:`difflib.SequenceMatcher` computes the
*same* ratio, so this module is a dependency-free stand-in with identical semantics on the
values that matter to the matcher and validator. Swapping in rapidfuzz behind this function
is a one-line change and does not alter any threshold.
"""

from __future__ import annotations

from difflib import SequenceMatcher

__all__ = ["ratio"]


def ratio(a: str, b: str) -> float:
    """Similarity of ``a`` and ``b`` in ``[0, 100]`` (rapidfuzz.fuzz.ratio-compatible)."""
    if not a and not b:
        return 100.0
    return SequenceMatcher(None, a, b).ratio() * 100.0
