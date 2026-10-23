"""Person-requested privacy operations through an authenticated linked helper.

Full CSV is an assisted exercise of the person's export request, not ordinary
carer progress access. The browser must implement a separate deletion screen.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ..store.privacy import PrivacyConflict, PrivacyStore
from .console_auth import ConsoleAccess, console_access

router = APIRouter(prefix="/api/console", tags=["privacy"])
Access = Annotated[ConsoleAccess, Depends(console_access)]


class PersonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=False)
    person_confirmed: StrictBool = Field(alias="personConfirmed")

    @field_validator("person_confirmed")
    @classmethod
    def must_confirm(cls, value):
        if value is not True:
            raise ValueError("The person must explicitly request this operation")
        return value


class DeleteRequest(PersonRequest):
    confirmation_token: str = Field(alias="confirmationToken", min_length=32, max_length=128)


def _privacy(access):
    if access.demo:
        raise HTTPException(403, "Privacy operations require a real linked helper credential")
    return PrivacyStore(access.store)


def _person(request, person):
    # Resolve without requiring a surviving link: a successful deletion can be retried.
    return request.app.state.pl.people.get(person, person)


def _error(exc):
    if isinstance(exc, PrivacyConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(403, "Linked helper required")
    if isinstance(exc, KeyError):
        return HTTPException(404, "Person or receipt not found")
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    # Never include database/provider exception contents in the response.
    return HTTPException(503, "Privacy operation failed; no completion is confirmed")


async def _perform(request, person, access, action):
    privacy = _privacy(access)
    pid = _person(request, person)
    registry = request.app.state.pl.sessions
    if not await registry.claim(pid):
        raise HTTPException(409, "Finish practice or plan generation before this operation")
    try:
        return action(privacy, pid)
    except Exception as exc:
        raise _error(exc) from None
    finally:
        await registry.release(pid)


@router.post("/privacy/{person}/export")
async def export_person(person: str, body: PersonRequest, request: Request, access: Access):
    csv = await _perform(request, person, access,
        lambda privacy, pid: privacy.export(pid, access.user_id,
                                           person_confirmed=body.person_confirmed))
    return Response(csv, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="patient-listener-export.csv"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/privacy/{person}/deletion-request")
async def deletion_request(person: str, request: Request, access: Access):
    return await _perform(request, person, access,
        lambda privacy, pid: privacy.request_deletion(pid, access.user_id))


@router.delete("/privacy/{person}")
async def delete_person(person: str, body: DeleteRequest, request: Request, access: Access):
    return await _perform(request, person, access,
        lambda privacy, pid: privacy.confirm_deletion(pid, access.user_id,
            body.confirmation_token, person_confirmed=body.person_confirmed))


@router.get("/deletions/{receipt_id}")
async def deletion_receipt(receipt_id: str, access: Access):
    privacy = _privacy(access)
    try:
        return privacy.receipt(receipt_id, access.user_id)
    except Exception as exc:
        raise _error(exc) from None
