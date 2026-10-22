"""Therapist console REST API, backed by the real :class:`SqliteStore`.

Replaces the mock ``DATA`` object in ``web/console.html`` with live, row-scoped reads of the
store the patient app writes to. Linked carers/therapists create drafts; approval follows
the linked-role policy (FR-40). Agents cannot use console credentials to approve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..types import Need, Outcome
from .console_auth import ConsoleAccess, console_access

__all__ = ["router"]

router = APIRouter(prefix="/api/console", tags=["console"])
Access = Annotated[ConsoleAccess, Depends(console_access)]

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


def _resolve(request: Request, person: str, access: ConsoleAccess) -> str:
    """Accept either a persona key ('margaret') or a full person id ('demo-margaret')."""
    state = _state(request)
    pid = state.people.get(person, person)
    if pid not in access.store.linked_people(access.user_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return pid


@router.get("/me")
async def me(access: Access) -> dict:
    return {"id": access.user_id, "name": access.display_name,
            "role": access.role, "demo": access.demo}


@router.post("/logout")
async def logout(request: Request, access: Access) -> dict:
    token = request.headers["authorization"].partition(" ")[2]
    access.store.revoke_console_token(token)
    return {"ok": True}


@router.post("/demo/session")
async def demo_session(request: Request) -> JSONResponse:
    store = _state(request).console_demo_store
    if store is None:
        raise HTTPException(404, "Demo console is disabled")
    token = store.issue_console_token("judge-demo", ttl_s=3600, demo=True)
    return JSONResponse({"token": token, "demo": True}, headers={"Cache-Control": "no-store"})


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
async def caseload(request: Request, access: Access) -> dict:
    state = _state(request)
    store = access.store
    aliases = {pid: key for key, pid in state.people.items()}
    out = []
    for pid in store.linked_people(access.user_id):
        needs = store.person_needs(pid)
        out.append(
            {
                "id": aliases.get(pid, pid),
                "name": store.person_name(pid),
                "needs": [_NEED_LABEL.get(n, n.value) for n in needs],
                "last": _last_seen(store, pid),
                "returned": store.count_found_without_hint(pid, since_days=30),
                "canApprove": access.role == "therapist" or not store.has_linked_therapist(pid),
            }
        )
    return {"therapist": {"name": access.display_name}, "caseload": out}


@router.get("/words/{person}")
async def words(request: Request, person: str, access: Access) -> dict:
    store = access.store
    pid = _resolve(request, person, access)
    return {"person": person, "words": [_word_dict(w) for w in store.all_words(pid)]}


class WordDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=60)
    kind: Literal["person", "place", "food", "object", "activity", "phrase"]
    meaning_cue: str = Field(default="", max_length=90)
    first_sound: str = Field(default="", max_length=4)

    @field_validator("text", "meaning_cue", "first_sound")
    @classmethod
    def single_line(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Use a single line without control characters")
        return value


@router.post("/words/{person}", status_code=201)
async def create_word_draft(request: Request, person: str, draft: WordDraftInput,
                            access: Access) -> dict:
    pid = _resolve(request, person, access)
    try:
        word = access.store.console_add_word_draft(pid, actor=access.user_id,
                                                  **draft.model_dump())
    except PermissionError as exc:
        raise HTTPException(403, "Draft creation is not permitted") from exc
    return {"ok": True, "word": _word_dict(word)}


@router.get("/grid/{person}")
async def grid(request: Request, person: str, access: Access) -> dict:
    store = access.store
    pid = _resolve(request, person, access)
    if access.role != "therapist":
        raise HTTPException(403, "Detailed progress is only available to the linked therapist")
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


def _settings_payload(person: str, pid: str, access: ConsoleAccess) -> dict:
    from ..profile_settings import profile_values
    cfg = access.store.person_pause(pid)
    return {
        "person": person,
        "needs": [_NEED_LABEL.get(n, n.value) for n in sorted(cfg.needs, key=lambda n:n.value)],
        "needKeys": sorted(n.value for n in cfg.needs),
        "hintOrder": "meaning-first" if cfg.hint_order[0].name == "MEANING" else "sound-first",
        "hintWait": cfg.offer_hint_s,
        "backchannelWait": cfg.backchannel_s,
        "maxWait": cfg.max_wait_s,
        "sessionMin": cfg.max_session_min,
        "canEdit": access.store.can_manage_profile(pid, access.user_id),
        "values": profile_values(cfg),
    }


class ProfileSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    needs: list[str] | None = None
    hint_order: list[str] | None = None
    backchannel_s: float | None = Field(default=None, ge=2, le=15)
    offer_hint_s: float | None = Field(default=None, ge=4, le=15)
    max_wait_s: float | None = Field(default=None, ge=8, le=120)
    max_session_min: int | None = Field(default=None, ge=3, le=120)


@router.get("/settings/{person}")
async def settings(request: Request, person: str, access: Access) -> dict:
    pid = _resolve(request, person, access)
    return _settings_payload(person, pid, access)


@router.patch("/settings/{person}")
async def save_settings(request: Request, person: str, changes: ProfileSettingsInput,
                        access: Access) -> dict:
    pid = _resolve(request, person, access)
    try:
        access.store.console_update_profile(pid, changes.model_dump(exclude_unset=True),
                                            actor=access.user_id)
    except PermissionError as exc:
        raise HTTPException(403, "Only the linked therapist, or carer without a therapist, can change settings") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _settings_payload(person, pid, access)


@router.get("/consent/{person}")
async def consent(request: Request, person: str, access: Access) -> dict:
    store = access.store
    pid = _resolve(request, person, access)
    return {
        "person": person,
        "tellCarerLowMood": store.has_consent(pid, "tell_carer_low_mood"),
        "dataSharing": store.has_consent(pid, "data_sharing"),
        "shareWithTherapist": store.has_consent(pid, "share_with_therapist"),
    }


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    personConfirmed: Literal[True]
    tellCarerLowMood: bool | None = None
    dataSharing: bool | None = None
    shareWithTherapist: bool | None = None

    @field_validator("personConfirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation must be true")
        return value


@router.patch("/consent/{person}")
async def save_consent(request: Request, person: str, changes: ConsentInput,
                       access: Access) -> dict:
    pid = _resolve(request, person, access)
    keys = {"tellCarerLowMood": "tell_carer_low_mood", "dataSharing": "data_sharing",
            "shareWithTherapist": "share_with_therapist"}
    values = changes.model_dump(exclude_unset=True)
    confirmed = values.pop("personConfirmed")
    try:
        access.store.console_update_consent(pid, {keys[k]: v for k, v in values.items()},
                                            actor=access.user_id, person_confirmed=confirmed)
    except PermissionError as exc:
        raise HTTPException(403, "Only a linked helper can record consent") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await consent(request, person, access)


@router.post("/words/{person}/{word_id}/approve")
async def approve(request: Request, person: str, word_id: str, access: Access) -> dict:
    store = access.store
    pid = _resolve(request, person, access)
    try:
        w = store.console_approve_word(pid, word_id, actor=access.user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="Word not found")
    return {"ok": True, "word": _word_dict(w)}


class PlanGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_words: int = Field(default=1, ge=1, le=10)
    use_ai: bool = False
    render_audio: bool = True


@router.post("/plans/{person}/generate")
async def generate_person_plan(request: Request, person: str, options: PlanGenerationInput,
                               access: Access) -> dict:
    import importlib.util
    from ..llm.factory import build_llm
    from ..plan_generation import generate_plan, PlanConflict
    from .nemo_stream import synthesize
    from .voice_connection import worker_call
    state = _state(request)
    pid = _resolve(request, person, access)
    if not access.store.can_manage_profile(pid, access.user_id):
        raise HTTPException(403, "Only the linked therapist, or carer without a therapist, can generate plans")
    if access.demo and (options.use_ai or options.render_audio):
        raise HTTPException(403, "Judge demo plan generation supports templates and text only")
    runtime = request.app.state.voice_runtime
    if options.render_audio and runtime is None:
        raise HTTPException(503, "Voice models are not loaded; use render_audio=false for a text plan")
    if options.use_ai and (not access.store.is_ai_enabled() or not state.settings.nebius_api_key.strip()
                          or importlib.util.find_spec('openai') is None):
        raise HTTPException(409, "Enable AI and configure the API key and SDK before requesting model hints")
    # Same admission controls as live practice. A generation cannot compete with voice
    # or mutate the person's hints under an active session on this worker.
    person_key = ('demo-plan:' if access.demo else '') + pid
    if not await state.sessions.claim(person_key):
        raise HTTPException(409, "This person has an active session or plan generation")
    gpu_claimed = False
    try:
        if options.render_audio:
            if not await state.sessions.claim('__gpu_voice__'):
                raise HTTPException(409, "GPU is busy; stop the voice session before generating audio")
            gpu_claimed = True
        async def render(text):
            def locked_render():
                with runtime.gpu_lock:
                    return synthesize(runtime, text)
            return await worker_call(locked_render)
        return await generate_plan(access.store, pid, actor=access.user_id,
            llm=build_llm(state.settings, access.store), max_words=options.max_words,
            use_ai=options.use_ai, render=render if options.render_audio else None,
            tts_model=state.settings.tts_model, voice=state.settings.tts_voice)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(403, "Plan generation is no longer permitted") from exc
    except PlanConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        # Never include model payloads, keys or text in an error response.
        raise HTTPException(503, "Plan generation failed; the previous plan was kept") from exc
    finally:
        if gpu_claimed:
            await state.sessions.release('__gpu_voice__')
        await state.sessions.release(person_key)
