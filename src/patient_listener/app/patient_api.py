"""One-time helper enrollment; no patient password and no credential in JSON/URL."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from ..store.patient_access import PatientAccess
from .console_auth import ConsoleAccess, console_access

router = APIRouter(tags=['patient enrollment'])
Access = Annotated[ConsoleAccess, Depends(console_access)]
COOKIE = 'pl_patient_link'
COOKIE_MAX_AGE = 365 * 24 * 3600


class Enrollment(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    setup_code: str = Field(min_length=32,max_length=128)


def _transport(request):
    from .server import _is_secure
    cfg = request.app.state.settings
    if cfg.require_https and not _is_secure(request.headers,request.url.scheme,
                                            trust_proxy_headers=cfg.trust_proxy_headers):
        raise HTTPException(400,'HTTPS is required')


def _helper(request, person, access):
    _transport(request)
    if access.demo:
        raise HTTPException(403,'Device setup requires a real linked helper credential')
    return PatientAccess(access.store),request.app.state.pl.people.get(person,person)


def _error(exc):
    if isinstance(exc,PermissionError): return HTTPException(403,'Linked helper required')
    if isinstance(exc,KeyError): return HTTPException(404,'Person not found')
    if isinstance(exc,ValueError): return HTTPException(400,'Invalid or expired setup code or device')
    return HTTPException(503,'Device operation failed; no completion confirmed')


@router.post('/api/console/patients/{person}/device-links')
async def create_link(person: str, request: Request, access: Access):
    store,pid = _helper(request,person,access)
    try: return store.create_invite(pid,access.user_id)
    except Exception as exc: raise _error(exc) from None


@router.get('/api/console/patients/{person}/devices')
async def devices(person: str, request: Request, access: Access):
    store,pid = _helper(request,person,access)
    try: return {'devices':store.list_devices(pid,access.user_id)}
    except Exception as exc: raise _error(exc) from None


@router.delete('/api/console/patients/{person}/devices/{authorization_id}')
async def revoke_device(person: str, authorization_id: str, request: Request, access: Access):
    store,pid = _helper(request,person,access)
    try: return store.revoke(pid,authorization_id,access.user_id)
    except Exception as exc: raise _error(exc) from None


@router.post('/api/patient/enroll')
async def enroll(body: Enrollment, request: Request):
    _transport(request)
    try:
        result = PatientAccess(request.app.state.pl.store).redeem(
            body.setup_code,request.headers.get('x-pl-device',''))
    except (KeyError,PermissionError,ValueError):
        raise HTTPException(400,'Invalid or expired setup code or device') from None
    except Exception:
        raise HTTPException(503,'Device setup failed; retry with the same setup code') from None
    secret = result.pop('credential')
    response = JSONResponse({'linked':True,**result},headers={'Cache-Control':'no-store'})
    response.set_cookie(COOKIE,secret,max_age=COOKIE_MAX_AGE,httponly=True,
        secure=request.app.state.settings.require_https,samesite='strict',path='/api/session')
    return response


class PatientWaitInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    backchannel_s: float | None = None
    offer_hint_s: float | None = None
    max_wait_s: float | None = None
    max_session_min: int | None = None


def _patient(request: Request, person: str) -> tuple:
    """Patient cookie and device authorize exactly one person, never a console token."""
    _transport(request)
    state = request.app.state.pl
    pid = state.people.get(person, person)
    try:
        authorization = PatientAccess(state.store).credential_authorization(
            pid, request.headers.get('x-pl-device', ''), request.cookies.get(COOKIE, ''))
    except ValueError:
        authorization = None
    if authorization is None:
        raise HTTPException(401, 'Device setup is required')
    return state, pid


@router.get('/api/session/me')
async def enrolled_patient(request: Request):
    """Restore the enrolled browser's patient and merged needs without a persona guess."""
    from ..profile_settings import profile_values
    _transport(request)
    state = request.app.state.pl
    try:
        pid = PatientAccess(state.store).person_for_credential(
            request.headers.get('x-pl-device', ''), request.cookies.get(COOKIE, ''))
    except ValueError:
        pid = None
    if pid is None:
        raise HTTPException(401, 'Device setup is required')
    cfg = state.store.person_pause(pid)
    return JSONResponse({'person_id': pid, 'name': state.store.person_name(pid),
                         'needs': sorted(need.value for need in cfg.needs),
                         'settings': profile_values(cfg)}, headers={'Cache-Control': 'no-store'})


@router.get('/api/session/settings')
async def patient_settings(request: Request, person: str = 'margaret'):
    from ..profile_settings import profile_values
    state, pid = _patient(request, person)
    return JSONResponse({'person_id': pid, 'settings': profile_values(state.store.person_pause(pid))},
                        headers={'Cache-Control': 'no-store'})


@router.patch('/api/session/settings')
async def extend_patient_settings(request: Request, changes: PatientWaitInput,
                                   person: str = 'margaret'):
    from ..profile_settings import profile_values
    state, pid = _patient(request, person)
    # HTTP changes are for a not-yet-started session. An active socket must update
    # its own controller using extend_settings, not just change persisted values.
    if not await state.sessions.claim(pid):
        raise HTTPException(409, 'Use extend_settings on the active practice WebSocket')
    try:
        cfg = state.store.patient_extend_profile(pid, changes.model_dump(exclude_unset=True))
    except PermissionError:
        raise HTTPException(403, 'You may only lengthen or switch off waits and the session cap') from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await state.sessions.release(pid)
    return JSONResponse({'ok': True, 'person_id': pid, 'applies_to': 'next_session',
                         'settings': profile_values(cfg)}, headers={'Cache-Control': 'no-store'})
