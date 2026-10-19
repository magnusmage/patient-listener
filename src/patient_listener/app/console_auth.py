"""Console identities come from provisioned credentials, never client-supplied roles."""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from ..store.sqlite_store import SqliteStore


@dataclass(frozen=True)
class ConsoleAccess:
    user_id: str
    display_name: str
    role: str
    store: SqliteStore
    demo: bool = False


def console_access(request: Request) -> ConsoleAccess:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise HTTPException(401, "Sign in to the console", headers={"WWW-Authenticate": "Bearer"})
    state = request.app.state.pl
    demo = token.startswith("pldemo_")
    store = state.console_demo_store if demo else state.store
    user = store.console_user_for_token(token) if store else None
    if user is None:
        raise HTTPException(401, "Invalid or expired access token",
                            headers={"WWW-Authenticate": "Bearer"})
    if user["role"] not in {"therapist", "carer"}:
        raise HTTPException(403, "This role cannot access the console")
    return ConsoleAccess(user["id"], user["display_name"], user["role"], store, demo)
