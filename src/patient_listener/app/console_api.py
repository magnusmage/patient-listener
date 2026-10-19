"""Therapist console REST API, backed by the real :class:`SqliteStore`.

Replaces the mock ``DATA`` object in ``web/console.html`` with live, row-scoped reads of the
store the patient app writes to. Everything is read-only except the one write the console is
allowed to make: approving a word draft (FR-40 - a therapist, never the agent).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from ..types import Need, Outcome, WordStatus

__all__ = ["router"]

router = APIRouter(prefix="/api/console", tags=["console"])

_NEED_LABEL = {
    Need.FINDING_WORDS: "Finding the word",
    Need.WORDS_OUT: "Getting words started",
    Need.BEING_HEARD: "Being loud enough",
    Need.BEING_CLEAR: "Being clear",
    Need.SAVING_ENERGY: "Getting tired",
    Need.LISTENING: "Listening",
}


def _state(request: Request):
    return request.app.state.pl


def _resolve(request: Request, person: str) -> str:
    """Accept either a persona key ('margaret') or a full person id ('demo-margaret')."""
    state = _state(request)
    if person in state.people:
        return state.people[person]
    if person in state.people.values():
        return person
    raise HTTPException(status_code=404, detail=f"unknown person: {person}")


def _word_dict(w) -> dict:  # noqa: ANN001 - WordEntry
    return {
        "id": w.id,
        "text": w.text,
        "kind": w.kind,
        "cue": w.meaning_cue,
        "first": w.first_sound,
        "status": w.status.value,
        "by": w.approved_by or w.added_by,
    }


def _last_seen(store, pid: str) -> str:  # noqa: ANN001
    rows = store.attempts_for(pid)
    if not rows:
        return "—"
    last = max(r["at"] for r in rows)
    day = datetime.fromisoformat(last).date()
    today = datetime.now(timezone.utc).date()
    delta = (today - day).days
    return {0: "Today", 1: "Yesterday"}.get(delta, f"{delta} days ago")


@router.get("/caseload")
async def caseload(request: Request) -> dict:
    state = _state(request)
    store = state.store
    out = []
    for key, pid in state.people.items():
        needs = store.person_needs(pid)
        out.append(
            {
                "id": key,
                "name": store.person_name(pid),
                "needs": [_NEED_LABEL.get(n, n.value) for n in needs],
                "last": _last_seen(store, pid),
                "returned": store.count_found_without_hint(pid, since_days=30),
            }
        )
    return {"therapist": {"name": "Sam (SLT)"}, "caseload": out}


@router.get("/words/{person}")
async def words(request: Request, person: str) -> dict:
    store = _state(request).store
    pid = _resolve(request, person)
    return {"person": person, "words": [_word_dict(w) for w in store.all_words(pid)]}


@router.get("/grid/{person}")
async def grid(request: Request, person: str) -> dict:
    store = _state(request).store
    pid = _resolve(request, person)
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=4 - i)) for i in range(5)]
    labels = [d.strftime("%a") for d in days]

    def cell_for(word_id: str, day) -> str:  # noqa: ANN001
        best = "none"
        rank = {"none": 0, "word": 1, "sound": 2, "meaning": 3, "check": 4}
        for r in store.attempts_for(pid):
            if r["word_id"] != word_id:
                continue
            if datetime.fromisoformat(r["at"]).date() != day:
                continue
            code = _cell_code(r)
            if rank[code] > rank[best]:
                best = code
        return best

    rows = []
    for w in store.words(pid):
        rows.append({"word": w.text, "cells": [cell_for(w.id, d) for d in days]})
    return {"person": person, "days": labels, "rows": rows}


def _cell_code(row: dict) -> str:
    if row["outcome"] == Outcome.FOUND.value:
        return {0: "check", 1: "meaning", 2: "sound", 3: "word"}.get(int(row["hint_level"]), "check")
    if row["outcome"] == Outcome.REPEATED.value:
        return "word"
    return "none"


@router.get("/settings/{person}")
async def settings(request: Request, person: str) -> dict:
    store = _state(request).store
    pid = _resolve(request, person)
    from ..voice.merge import merge

    cfg = merge(store.person_needs(pid))
    return {
        "person": person,
        "needs": [_NEED_LABEL.get(n, n.value) for n in store.person_needs(pid)],
        "hintOrder": "meaning-first" if cfg.hint_order[0].name == "MEANING" else "sound-first",
        "hintWait": cfg.offer_hint_s,
        "sessionMin": cfg.max_session_min,
    }


@router.get("/consent/{person}")
async def consent(request: Request, person: str) -> dict:
    store = _state(request).store
    pid = _resolve(request, person)
    return {
        "person": person,
        "tellCarerLowMood": store.has_consent(pid, "tell_carer_low_mood"),
        "dataSharing": store.has_consent(pid, "data_sharing"),
    }


@router.post("/words/{person}/{word_id}/approve")
async def approve(request: Request, person: str, word_id: str) -> dict:
    store = _state(request).store
    _resolve(request, person)  # validate person
    try:
        w = store.approve_word(word_id, by="slt")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown word: {word_id}")
    return {"ok": True, "word": _word_dict(w)}
