"""Workbook D-14/D-16: Jellyfish matching and precomputed English first phonemes.

No corpus download, network request or pronunciation lookup occurs in the matcher.
CMUdict is loaded locally through NLTK. Out-of-dictionary names use Epitran/Flite.
"""
from __future__ import annotations

from functools import lru_cache
import re
import shutil
import subprocess
import unicodedata

from jellyfish import metaphone as _metaphone


class PronunciationError(ValueError):
    """A word needs a human-supplied first sound rather than an invented guess."""


class PronunciationUnavailable(RuntimeError):
    """The local pronunciation resources have not been installed."""


def metaphone(word: str) -> str:
    return _metaphone(word)


@lru_cache(maxsize=1)
def _dictionary() -> dict:
    try:
        from nltk.corpus import cmudict
        return cmudict.dict()
    except (ImportError, LookupError):
        raise PronunciationUnavailable(
            "Install NLTK and its cmudict corpus, or supply first_sound explicitly") from None


@lru_cache(maxsize=1)
def _epitran():
    if not shutil.which("lex_lookup"):
        raise PronunciationUnavailable(
            "Install Flite lex_lookup for Epitran English names, or supply first_sound explicitly")
    try:
        from epitran import Epitran
        from epitran.flite import FliteLexLookup

        class BoundedFlite(FliteLexLookup):
            def english_g2p(self, text):
                # Epitran 1.35.2 has no process timeout. Keep its conversion but bound
                # the external English lookup; no shell and no patient-text logging.
                completed = subprocess.run(
                    ["lex_lookup", self.normalize(text).lower()], capture_output=True,
                    check=True, timeout=2)
                lines = completed.stdout.decode("utf-8").splitlines()
                return self.arpa_to_ipa(lines[0] if lines else "")

        converter = Epitran("eng-Latn")
        converter.epi = BoundedFlite()
        return converter
    except Exception:
        raise PronunciationUnavailable(
            "Epitran English setup failed; check pronunciation_check or supply first_sound explicitly") from None


# Epitran English IPA to the existing <=4-character ARPAbet storage contract.
_IPA_TO_ARPA = {
    "t͡ʃ": "CH", "d͡ʒ": "JH", "tʃ": "CH", "dʒ": "JH", "ɹ̩": "ER",
    "ej": "EY", "eɪ": "EY", "aj": "AY", "aɪ": "AY", "ow": "OW", "oʊ": "OW",
    "aw": "AW", "aʊ": "AW", "oj": "OY", "ɔɪ": "OY",
    "æ": "AE", "i": "IY", "ɛ": "EH", "ɪ": "IH", "ɑ": "AA", "ɔ": "AO",
    "ʌ": "AH", "ə": "AH", "u": "UW", "ʊ": "UH", "ɚ": "ER", "ɜ": "ER",
    "b": "B", "d": "D", "f": "F", "ɡ": "G", "g": "G", "h": "HH",
    "k": "K", "l": "L", "m": "M", "n": "N", "ŋ": "NG", "p": "P",
    "ɹ": "R", "r": "R", "s": "S", "ʃ": "SH", "t": "T", "ð": "DH",
    "θ": "TH", "v": "V", "w": "W", "j": "Y", "z": "Z", "ʒ": "ZH",
}


def _ipa_first(ipa: str) -> str:
    ipa = unicodedata.normalize("NFC", ipa).lstrip(" ˈˌ")
    for segment in sorted(_IPA_TO_ARPA, key=len, reverse=True):
        if ipa.startswith(segment):
            return _IPA_TO_ARPA[segment]
    raise PronunciationError("Could not derive the first sound; supply first_sound explicitly")


def first_sound(word: str) -> str:
    """Return a stress-free ARPAbet first phoneme, never the first spelling letter."""
    match = re.search(r"[^\W\d_]+(?:['’][^\W\d_]+)*", word, re.UNICODE)
    if not match:
        raise PronunciationError("Use a word with letters or supply first_sound explicitly")
    token = match.group().replace("’", "'").lower()
    latin = ''.join(c for c in unicodedata.normalize("NFKD", token)
                    if not unicodedata.combining(c))
    variants = _dictionary().get(token) or _dictionary().get(latin)
    if variants and variants[0]:
        return re.sub(r"[0-2]$", "", variants[0][0]).upper()
    # English fallback only. Other scripts need a human-provided pronunciation.
    if not re.fullmatch(r"[a-z]+(?:'[a-z]+)*", latin):
        raise PronunciationError("Supply first_sound explicitly for this name's pronunciation")
    try:
        ipa = _epitran().transliterate(latin)
    except PronunciationUnavailable:
        raise
    except Exception:
        raise PronunciationError("Name pronunciation failed; supply first_sound explicitly") from None
    return _ipa_first(ipa)
