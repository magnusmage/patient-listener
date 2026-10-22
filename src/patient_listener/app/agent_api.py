"""The two agent tools. No chat ingestion, approvals or detailed patient reads."""
from dataclasses import dataclass, field
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from .console_api import WordDraftInput
from ..store.agent_store import AgentStore, RequestConflict

router = APIRouter(prefix='/api/agent/tools', tags=['agent tools'])


@dataclass
class AgentAccess:
    store: AgentStore
    token: str = field(repr=False)


def agent_access(request: Request) -> AgentAccess:
    scheme, _, token = request.headers.get('authorization','').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 256:
        raise HTTPException(401, 'Agent authentication required')
    adapter = AgentStore(request.app.state.pl.store)
    try:
        adapter.resolve(token)
    except PermissionError as exc:
        raise HTTPException(401, 'Invalid or expired agent credential') from exc
    return AgentAccess(adapter, token)


Access = Annotated[AgentAccess, Depends(agent_access)]


@router.post('/add_word_draft')
async def add_word_draft(draft: WordDraftInput, access: Access,
    request_id: Annotated[str, Header(alias='Idempotency-Key', min_length=1,
                                      max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]) -> dict:
    try:
        result = access.store.add_word_draft(access.token, request_id, **draft.model_dump())
    except PermissionError as exc:
        raise HTTPException(401, 'Agent access is no longer permitted') from exc
    except RequestConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**result, 'console_path':'/console.html'}


@router.get('/progress_summary')
async def progress_summary(access: Access) -> dict:
    try:
        return access.store.progress_summary(access.token)
    except PermissionError as exc:
        raise HTTPException(401, 'Agent access is no longer permitted') from exc
