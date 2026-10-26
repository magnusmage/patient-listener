"""Synthetic authenticated echo service for workbook G-02; no patient/API credentials."""
import hmac
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def create_app():
    token = os.environ.get('PL_PROBE_TOKEN', '')
    if len(token) < 32 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('Set a disposable PL_PROBE_TOKEN of at least 32 printable characters')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/livez')
    async def live():
        return {'status': 'synthetic_probe_only'}

    @app.websocket('/echo')
    async def echo(ws: WebSocket):
        authorization = ws.headers.get('authorization', '')
        if not hmac.compare_digest(authorization.encode(), ('Bearer '+token).encode()):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                message = await ws.receive()
                if message['type'] == 'websocket.disconnect':
                    break
                payload = message.get('bytes')
                if payload is None or not 1 <= len(payload) <= 64:
                    await ws.close(code=1009)
                    break
                await ws.send_bytes(payload)
        except WebSocketDisconnect:
            pass
    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_app(), host='0.0.0.0', port=int(os.environ.get('PL_PORT', '8000')),
                access_log=False, proxy_headers=False, ws_max_size=64)
