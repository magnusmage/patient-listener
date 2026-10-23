"""FastAPI application: serves the frontend, issues session tokens, and runs the real decision
core over a WebSocket. The pure core is untouched; this is the adapter that wires it to ``web/``.

Run it::

    pip install -e '.[api]'
    patient-listener-server            # or: uvicorn 'patient_listener.app.server:create_app' --factory

Then open http://localhost:8000/ (patient app, server mode) and /console.html (therapist console).
"""

from __future__ import annotations

import asyncio
import logging
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings, settings as default_settings

from .access_log import install_access_log_redaction, redact_request_target
from .voice_connection import VoiceConnection
from ..llm.factory import build_llm
from .console_api import router as console_router
from .agent_api import router as agent_router
from .deps import build_state
from .session import AppSession
from .voice_runtime import VoiceRuntime

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
    app.state.voice_runtime = None
    app.state.nightly_task = None
    db_path = os.environ.get("PL_DB_PATH")
    if (app.state.settings.nightly_enabled and not app.state.settings.database_url.startswith(
            ('postgresql://','postgresql+asyncpg://','postgres://'))
            and (db_path == ':memory:' or (db_path is None and app.state.settings.database_url.endswith('/:memory:')))):
        raise ValueError("Nightly scheduling requires a persistent PL_DB_PATH")
    app.state.pl = build_state(db_path=db_path,
                               settings=app.state.settings)
    try:
        if app.state.settings.voice_enabled:
            # Load once per worker, not once per patient. This stage does not enable streaming.
            app.state.voice_runtime = await asyncio.to_thread(
                VoiceRuntime.load, app.state.settings
            )
            logging.getLogger(__name__).info("GPU voice models loaded; development streaming enabled")
        if app.state.settings.nightly_enabled:
            from .nightly_worker import NightlyWorker
            app.state.nightly_task = asyncio.create_task(NightlyWorker(app).run())
        yield
    finally:
        if app.state.nightly_task is not None:
            app.state.nightly_task.cancel()
            await asyncio.gather(app.state.nightly_task, return_exceptions=True)
        if app.state.voice_runtime is not None:
            await asyncio.to_thread(app.state.voice_runtime.close)
            app.state.voice_runtime = None
        app.state.pl.store.close()
        if app.state.pl.console_demo_store is not None:
            app.state.pl.console_demo_store.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    # Uvicorn can start this factory directly, bypassing the package entry point. Install
    # redaction here so neither startup path writes session credentials to access logs.
    install_access_log_redaction()
    app = FastAPI(title="Patient Listener", lifespan=_lifespan)
    app.state.settings = settings or Settings()
    app.state.settings.assert_safe_startup()
    app.include_router(console_router)
    app.include_router(agent_router)

    @app.middleware("http")
    async def private_api_no_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/console/", "/api/agent/")) or request.url.path == "/api/session":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    async def health(request: Request) -> JSONResponse:
        runtime = request.app.state.voice_runtime
        voice_enabled = request.app.state.settings.voice_enabled
        pipeline_version = getattr(runtime, 'pipecat_version', None)
        pipeline_version = pipeline_version if isinstance(pipeline_version, str) else None
        # Do not advertise production voice readiness merely because weights loaded.
        return JSONResponse({
            "status": "voice_development" if voice_enabled else "text_ready",
            "voice_enabled": voice_enabled,
            "models_loaded": runtime is not None,
            "streaming_ready": False,
            "pipeline_framework": "pipecat" if pipeline_version else None,
            "pipecat_version": pipeline_version,
            "development_voice_enabled": runtime is not None,
        }, status_code=503 if voice_enabled else 200,
           headers={"Cache-Control": "no-store"})

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
                "voice_enabled": request.app.state.voice_runtime is not None,
            }
        )

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str = Query(""), device: str = Query(""),
                 voice: bool = Query(False)) -> None:
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
        runtime = websocket.app.state.voice_runtime
        gpu_claimed = False
        if voice:
            if runtime is None or not await state.sessions.claim("__gpu_voice__"):
                await state.sessions.release(claims.person_id)
                await websocket.close(code=1013, reason="Voice is unavailable or busy")
                return
            gpu_claimed = True
        app_session = connection = None
        try:
            await websocket.accept()
            async def direct_send(event: dict) -> None:
                await websocket.send_json(event)

            async def send(event: dict) -> None:
                if connection is not None:
                    await connection.send(event)
                else:
                    await direct_send(event)

            app_session = AppSession(store=state.store, person_id=claims.person_id, send=send,
                                     llm=build_llm(state.settings, state.store))
            if voice:
                connection = VoiceConnection(runtime, app_session, websocket, direct_send)
                await connection.start()
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if (text := message.get("text")) is not None:
                    control = json.loads(text)
                    if not isinstance(control, dict):
                        raise ValueError("Expected control object")
                    if control.get("type") == "playback_done" and connection is not None:
                        connection.acknowledge(control.get("id"))
                    else:
                        if connection is not None and control.get('type') in {'audio_settings', 'calibration_next'}:
                            connection.invalidate_input()
                        await app_session.handle(control)
                elif (frame := message.get("bytes")) is not None and connection is not None:
                    await connection.frame(frame)
        except WebSocketDisconnect:
            pass
        except (ValueError, asyncio.QueueFull):
            await websocket.close(code=1008, reason="Invalid or excessive input")
        finally:
            if app_session is not None:
                app_session.close()
            if connection is not None:
                await connection.close()
            if gpu_claimed:
                await state.sessions.release("__gpu_voice__")
            await state.sessions.release(claims.person_id)

    # Static frontend last, so /api/* and /ws win. html=True serves index.html at "/".
    web = _web_dir()
    if web.is_dir():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")

    return app
