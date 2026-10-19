"""Phonetic helpers for the word matcher and the sound hint.

* :func:`metaphone` is a dependency-free implementation of Lawrence Philips' original
  Metaphone, used for the "sounds like" component of the match score (FR-22). Production
  pins ``jellyfish~=1.2`` (D-16); ``jellyfish.metaphone`` implements the same algorithm, so
  it drops in behind this function with no threshold change.
* :func:`first_sound` returns the first letter used by the level-2 sound hint
  ("It starts with K."). Production derives the first phoneme from CMUdict via ``nltk`` with
  an ``epitran`` fallback (D-14); the uppercase first letter is the behaviour the hint shows
  and is what is stored in ``WordEntry.first_sound``.

The Metaphone here is verified against the DR-4 fixtures (Leo/leeoh/Leah, Biscuit/bisket,
kettle, teapot) and a set of canonical words in the test suite.
"""

from __future__ import annotations

__all__ = ["metaphone", "first_sound"]

_VOWELS = frozenset("AEIOU")
_FRONT = frozenset("EIY")  # letters that soften C and G


def _is_vowel(ch: str) -> bool:
    return ch in _VOWELS


def metaphone(word: str) -> str:
    """Return the Metaphone key of ``word`` (uppercase A-Z; empty for no letters)."""
    s = "".join(c for c in word.upper() if c.isalpha())
    if not s:
        return ""

    # Collapse doubled letters, except CC (which Metaphone keeps distinct, e.g. "accident").
    collapsed = [s[0]]
    for ch in s[1:]:
        if ch == collapsed[-1] and ch != "C":
            continue
        collapsed.append(ch)
    s = "".join(collapsed)
    n = len(s)

    # Initial-letter exceptions.
    if s[:2] in ("AE", "GN", "KN", "PN", "WR"):
        s = s[1:]
        n = len(s)
    elif s[:1] == "X":
        s = "S" + s[1:]
    elif s[:2] == "WH":
        s = "W" + s[2:]
        n = len(s)
    if not s:
        return ""
    n = len(s)

    out: list[str] = []
    i = 0
    while i < n:
        ch = s[i]
        prev = s[i - 1] if i > 0 else ""
        nxt = s[i + 1] if i + 1 < n else ""
        nxt2 = s[i + 2] if i + 2 < n else ""

        if ch in _VOWELS:
            # Vowels are kept only when they start the word.
            if i == 0:
                out.append(ch)
            i += 1
            continue

        if ch == "B":
            # Silent B at the end of a word after M ("dumb", "comb").
            if not (i == n - 1 and prev == "M"):
                out.append("B")
        elif ch == "C":
            if nxt == "I" and nxt2 == "A":  # -CIA- -> X (sh)
                out.append("X")
            elif nxt == "H":  # CH -> X (sh); SCH handled as C then H
                out.append("X")
                i += 1  # consume the H
            elif nxt in _FRONT:  # CE, CI, CY -> S, unless preceded by S (SCI/SCE/SCY)
                if prev != "S":
                    out.append("S")
            else:
                out.append("K")
        elif ch == "D":
            if nxt == "G" and nxt2 in _FRONT:  # DGE, DGI, DGY -> J
                out.append("J")
                i += 2  # consume G and the front vowel
            else:
                out.append("T")
        elif ch == "G":
            if nxt == "H":
                # GH: silent unless it starts a stressed syllable; treat as silent here
                # except when followed by a vowel (rare "ghetto" -> handled: keep K).
                if nxt2 and _is_vowel(nxt2):
                    out.append("K")
                i += 1  # consume H
            elif nxt == "N":
                # GN / GNED at end -> silent G.
                if i == n - 2 or (i == n - 4 and s[i + 2:] == "ED"):
                    pass
                else:
                    out.append("K")
            elif nxt in _FRONT and prev != "G":
                out.append("J")
            else:
                out.append("K")
        elif ch == "H":
            # H kept only when it starts a sound: after a vowel with a following vowel,
            # or at the start. Silent after a vowel at a word break, or after CSPTG digraphs.
            if (prev == "" or _is_vowel(prev)) and _is_vowel(nxt):
                out.append("H")
            elif prev not in ("C", "S", "P", "T", "G") and not _is_vowel(prev):
                out.append("H")
        elif ch == "J":
            out.append("J")
        elif ch == "K":
            if prev != "C":  # silent K after C ("acknowledge")
                out.append("K")
        elif ch == "L":
            out.append("L")
        elif ch == "M":
            out.append("M")
        elif ch == "N":
            out.append("N")
        elif ch == "P":
            out.append("F" if nxt == "H" else "P")
            if nxt == "H":
                i += 1
        elif ch == "Q":
            out.append("K")
        elif ch == "R":
            out.append("R")
        elif ch == "S":
            if nxt == "H":
                out.append("X")
                i += 1
            elif nxt == "I" and nxt2 in ("O", "A"):  # SIO, SIA -> X
                out.append("X")
            else:
                out.append("S")
        elif ch == "T":
            if nxt == "I" and nxt2 in ("O", "A"):  # TIO, TIA -> X
                out.append("X")
            elif nxt == "H":  # TH -> 0 (theta)
                out.append("0")
                i += 1
            else:
                out.append("T")
        elif ch == "V":
            out.append("F")
        elif ch == "W":
            if _is_vowel(nxt):
                out.append("W")
        elif ch == "X":
            out.append("K")
            out.append("S")
        elif ch == "Y":
            if _is_vowel(nxt):
                out.append("Y")
        elif ch == "Z":
            out.append("S")
        i += 1

    return "".join(out)


def first_sound(word: str) -> str:
    """First letter for the sound hint (CMUdict-derived first phoneme in production)."""
    for c in word:
        if c.isalpha():
            return c.upper()
    return ""
