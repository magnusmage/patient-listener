"""FastAPI application: serves the frontend, issues session tokens, and runs the real decision
core over a WebSocket. The pure core is untouched; this is the adapter that wires it to ``web/``.

Run it::

    pip install -e '.[api]'
    patient-listener-server            # or: uvicorn 'patient_listener.app.server:create_app' --factory

Then open http://localhost:8000/ (patient app, server mode) and /console.html (therapist console).
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings, settings as default_settings

from .access_log import install_access_log_redaction, redact_request_target
from .audio import build_pipeline
from .console_api import router as console_router
from .deps import build_state
from .session import AppSession

__all__ = ["create_app"]


def _web_dir() -> Path:
    override = os.environ.get("PL_WEB_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "web"


def _is_secure(headers, scheme: str, *, trust_proxy_headers: bool) -> bool:
    """Accept direct TLS, or the header from a configured trusted proxy."""
    if scheme.lower() in {"https", "wss"}:
        return True
    if not trust_proxy_headers:
        return False
    forwarded = headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return forwarded in {"https", "wss"}


def _redact_websocket_scope(scope: dict) -> None:
    """Remove credentials from the ASGI scope before Uvicorn writes its accept log.

    FastAPI has already copied query values into endpoint arguments when this runs. Mutating the
    scope therefore cannot affect authentication, while it provides a second safeguard for
    Uvicorn configurations that do not retain logger filters.
    """
    query = scope.get("query_string", b"")
    if isinstance(query, bytes):
        text = query.decode("utf-8", errors="replace")
    else:
        text = str(query)
    scope["query_string"] = redact_request_target(f"?{text}")[1:].encode("utf-8")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.pl = build_state(db_path=os.environ.get("PL_DB_PATH", ":memory:"),
                               settings=app.state.settings)
    try:
        yield
    finally:
        app.state.pl.store.close()
        if app.state.pl.console_demo_store is not None:
            app.state.pl.console_demo_store.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    # Uvicorn can start this factory directly, bypassing the package entry point. Install
    # redaction here so neither startup path writes session credentials to access logs.
    install_access_log_redaction()
    app = FastAPI(title="Patient Listener", lifespan=_lifespan)
    app.state.settings = settings or default_settings
    app.state.settings.assert_safe_startup()
    app.include_router(console_router)

    @app.middleware("http")
    async def private_api_no_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/console/") or request.url.path == "/api/session":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/session")
    async def session_token(
        request: Request, person: str = Query("margaret"), device: str = Query("")
    ) -> JSONResponse:
        state = request.app.state.pl
        if state.settings.require_https and not _is_secure(
            request.headers, request.url.scheme, trust_proxy_headers=state.settings.trust_proxy_headers
        ):
            return JSONResponse({"error": "HTTPS is required"}, status_code=400)
        pid = state.people.get(person, person)
        if pid not in state.people.values():
            return JSONResponse({"error": f"unknown person: {person}"}, status_code=404)
        # Header is preferred for the HTTP request; query support keeps a plain browser client
        # usable when it cannot attach a custom header. Neither value is logged or persisted.
        device = request.headers.get("x-pl-device", device)
        try:
            token = state.signer.issue(pid, device)
        except ValueError:
            return JSONResponse({"error": "A valid device identifier is required"}, status_code=400)
        scheme = "wss" if request.url.scheme == "https" else "ws"
        host = request.headers.get("host", "localhost:8000")
        needs = sorted(n.value for n in state.store.person_needs(pid))
        return JSONResponse(
            {
                "ws_url": f"{scheme}://{host}/ws",
                "token": token,
                "person": person,
                "needs": needs,
            }
        )

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str = Query(""), device: str = Query("")) -> None:
        _redact_websocket_scope(websocket.scope)
        state = websocket.app.state.pl
        if state.settings.require_https and not _is_secure(
            websocket.headers, websocket.url.scheme, trust_proxy_headers=state.settings.trust_proxy_headers
        ):
            await websocket.close(code=1008)
            return
        try:
            claims = state.signer.verify(token, device)
        except ValueError:
            await websocket.close(code=1008)  # policy violation: bad / expired token
            return
        if not await state.sessions.claim(claims.person_id):
            await websocket.close(code=1013, reason="Practice is already active on another device")
            return
        await websocket.accept()

        async def send(event: dict) -> None:
            await websocket.send_json(event)

        app_session = AppSession(store=state.store, person_id=claims.person_id, send=send)
        pipeline = build_pipeline(
            state.settings,
            on_speech=app_session.on_audio_speech,
            on_partial=app_session.on_audio_partial,
            on_final=app_session.on_audio_final,
            on_silence=app_session.on_audio_silence,
            send_audio=websocket.send_bytes,
            phrase_boosts=(word.text for word in app_session.words),
            boost_alpha=state.settings.boost_alpha,
            voice=state.settings.tts_voice,
        )
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if (text := message.get("text")) is not None:
                    await app_session.handle(json.loads(text))
                elif (frame := message.get("bytes")) is not None and pipeline is not None:
                    await pipeline.on_frame(frame)
        except WebSocketDisconnect:
            pass
        finally:
            app_session.close()
            await state.sessions.release(claims.person_id)

    # Static frontend last, so /api/* and /ws win. html=True serves index.html at "/".
    web = _web_dir()
    if web.is_dir():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")

    return app
