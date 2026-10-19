"""Shared test helpers."""

from __future__ import annotations

from patient_listener.schemas import HintLines, PauseConfig, WordEntry
from patient_listener.types import Need, WordStatus
from patient_listener.voice.actions import Action
from patient_listener.voice.controller import PatienceController
from patient_listener.voice.merge import merge


def word(
    wid: str = "w1",
    text: str = "Leo",
    kind: str = "person",
    meaning_cue: str = "your grandson, he's six",
    first_sound: str = "L",
    hints: HintLines | None = None,
) -> WordEntry:
    return WordEntry(
        id=wid,
        person_id="p",
        text=text,
        kind=kind,
        meaning_cue=meaning_cue,
        first_sound=first_sound,
        status=WordStatus.APPROVED,
        added_by="slt",
        approved_by="slt",
        hints=hints,
    )


def cfg_for(*needs: Need) -> PauseConfig:
    return merge(frozenset(needs)) if needs else PauseConfig()


def run_silence(ctrl: PatienceController, start: float, until: float, step: float = 0.1):
    """Drive ``on_silence`` over integer-tenths steps; return (time, action) pairs."""
    out: list[tuple[float, Action]] = []
    for i in range(round(start * 10), round(until * 10) + 1):
        t = i / 10
        for a in ctrl.on_silence(t):
            out.append((round(t, 1), a))
    return out
