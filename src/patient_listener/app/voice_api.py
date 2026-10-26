"""GPU-only private renderer. One capacity lease; no caller-controlled URLs/models."""
import asyncio
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from .remote_voice import contract, MAX_PCM
from .voice_connection import worker_call

router=APIRouter()


async def service_access(request: Request):
    from .server import _is_secure
    cfg=request.app.state.settings
    if cfg.require_https and not _is_secure(request.headers,request.url.scheme,trust_proxy_headers=cfg.trust_proxy_headers):
        raise HTTPException(400,'HTTPS is required')
    expected=cfg.voice_service_secret.encode()
    supplied=request.headers.get('x-pl-service-key','').encode()
    if not expected or not hmac.compare_digest(expected,supplied):
        raise HTTPException(401,'Service authorization required')


class RenderRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_strip_whitespace=True)
    person_id: str=Field(min_length=1,max_length=128)
    lease_owner: str=Field(min_length=32,max_length=128)
    text: str=Field(min_length=1,max_length=120)
    contract: str=Field(pattern='^[0-9a-f]{64}$')


@router.post('/internal/render',dependencies=[Depends(service_access)])
async def render(body: RenderRequest, request: Request):
    state=request.app.state.pl
    runtime=request.app.state.voice_runtime
    if runtime is None:raise HTTPException(503,'Voice runtime unavailable')
    if body.contract!=contract(state.settings):raise HTTPException(409,'Voice audio configuration mismatch')
    if not state.store.person_exists(body.person_id):raise HTTPException(404,'Person not found')
    if not await state.sessions.check_owner(body.person_id,body.lease_owner):
        raise HTTPException(409,'Caller no longer owns person admission')
    if not await state.sessions.claim('__gpu_voice__'):
        raise HTTPException(409,'Voice GPU is busy')
    try:
        from .nemo_stream import render_hint
        def synthesize():
            with runtime.gpu_lock:return render_hint(runtime,body.text)
        pcm=await worker_call(synthesize)
        await state.sessions.check_owned('__gpu_voice__')
        if not await state.sessions.check_owner(body.person_id,body.lease_owner):
            raise HTTPException(409,'Caller no longer owns person admission')
        if not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or len(pcm)>MAX_PCM:
            raise ValueError('Invalid PCM output')
        return Response(pcm,media_type='application/octet-stream',headers={
            'Cache-Control':'no-store','X-PL-Audio-Contract':body.contract})
    except HTTPException:raise
    except asyncio.CancelledError:
        if state.sessions.was_lost('__gpu_voice__'):
            raise HTTPException(503,'Voice admission lost') from None
        raise
    except Exception:
        raise HTTPException(503,'Voice rendering failed') from None
    finally:
        await state.sessions.release('__gpu_voice__')
