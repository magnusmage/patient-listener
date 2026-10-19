# Frontend ↔ Backend Integration — Design

Date: 2026-10-09
Status: approved (conversational), implementing

## Problem

The `web/` frontend and the Python decision core are **not connected**. The patient app
reimplements the controller's behaviour in JavaScript (`DemoEngine` in `web/client.js`); the
therapist console uses a hardcoded mock `DATA`. The frontend already defines a live contract —
`LiveDriver` opens a WebSocket to `window.PL_WS_URL` and exchanges a JSON event protocol — but
**no server fulfils it**. `fastapi`/`uvicorn` are declared as the `api` extra in
`pyproject.toml` yet no server module exists.

## Goal

Ship the "app API" the README repeatedly references: a FastAPI server that serves the frontend,
runs the **real** `SessionEngine`/`PatienceController` over a WebSocket speaking the exact event
protocol `web/app.js` already consumes, and backs the therapist console with real store data.
The pure core is not modified (ports-and-adapters invariant #3); everything new is an adapter
layer.

## Transports (two, one engine)

Both feed the identical `SessionEngine`:

1. **Text/logic transport** — works fully offline, no GPU. The browser sends control + text
   messages (the on-screen demo controls + typed input); the server runs the real controller,
   matcher, safety rules, hint ladder and patience timing. This is the testable integration.
2. **Audio transport (scaffold)** — binary 16 kHz frames → NeMo ASR adapter → controller;
   controller speech → Magpie TTS adapter → binary frames. Real adapter code behind the
   existing `Asr`/`Tts` ports, import-guarded and lazily constructed; **inert and untested
   offline** (needs the `voice` extra + GPU + weights). This is the documented deploy path.

## New package `src/patient_listener/app/`

| Module | Responsibility |
| --- | --- |
| `tokens.py` | HMAC-signed, 15-minute session tokens. `issue(person_id)` / `verify(token)`. Secret from a new `SESSION_TOKEN_SECRET` env (dev default). |
| `bridge.py` | **Pure** translation, no I/O: `action_to_events(action, ctx)` → list of event dicts; `client_message_to_event(msg)` → engine event tuple or control. Unit-tested in isolation. |
| `presenter.py` | Pure helpers: `WordEntry` → prompt dict (topic/photo/text by kind), safety card → `{title, body, number}`, loudness/time presentation keys. |
| `session.py` | `AppSession` per-connection orchestrator. Owns the word cursor + turn advancement, a monotonic session clock, and the asyncio **silence ticker** that re-feeds `("silence", now)` so the real controller fires `mm`/`offer_hint`/`move_on` at true elapsed times. Emits events via an async callback. |
| `audio.py` | Scaffold: `build_asr()`/`build_tts()` behind the ports; `None` when the extra/weights are absent. `frames_to_events` / `speak` wiring documented. |
| `console_api.py` | `APIRouter` with `/api/console/*` REST backed by `SqliteStore` + seed. |
| `deps.py` | App state: one seeded `SqliteStore`, `Settings`, token signer. |
| `server.py` | `create_app()` factory: static mount of `web/`, `/api/session`, `/ws`, console router. uvicorn entry `patient-listener-server`. |

## WebSocket protocol

`/ws?token=…` (token required; rejected with close code otherwise).

**Client → server (JSON):** `start`, `pause`, `speech`, `help`, `yes`, `no`,
`confirm_tap {ok}`, `typed {text}`, `demo_say {variant: exact|close|other|stroke}`, `done`,
`rest`, `resume`, `stop`. Binary messages are audio frames (audio transport only).

`demo_say` resolves against the current target **on the server** (only the server knows the
target), so matching/safety stay backend-authoritative: `exact`→`word.text`,
`close`→a near-miss in the 0.60–0.89 band, `other`→unrelated (<0.60), `stroke`→the stroke
phrase. Each becomes a `("heard", text, now)` engine event.

**Server → client (JSON):** the names `web/app.js` already listens for — `greeting`, `prompt`,
`state`, `backchannel`, `offerHint`, `hint`, `confirm`, `whatIHeard`, `loudness`, `found`,
`attempt`, `reply`, `moveOn`, `restOffer`, `checkComplete`, `safety`, `ended`.

### Action → event mapping (bridge)

- `Play("mm")` → `backchannel {key:"mm", caption:"mm"}`
- `Play("offer_hint")` → `offerHint {}`
- `Play("hint:…")` → (ignored in text mode; carried by `ShowHint`)
- `ShowHint(word, level)` → `hint {level, text, letter, word}` (text via `hints.render`)
- `Confirm(word)` → `confirm {word}`, **or** `whatIHeard {text}` when feedback is `what_i_heard`
- `Praise(word)` → `found {word, hintLevel}`
- `LogAttempt(a)` → `attempt {word_id, hint_level, outcome, score}`
- `MoveOn()` → `moveOn {}` then advance to next prompt
- `EndTurn()` → advance to next prompt (reply comes via `Speak`)
- `Speak(text)` → `reply {text}`
- `SafetyStop(card)` → `safety {card, title, body, number}` (via presenter)
- `Stop()` → `ended {reason, found}`
- `OfferRest()` → `restOffer {}`

Profile-specific presentation the core doesn't emit (loudness bar, time bar) is produced by
`AppSession`/`presenter` as a presentation concern, mirroring the existing `DemoEngine`.

## REST

- `GET /` and static → `web/` files.
- `GET /api/session?person=<id>` → `{ ws_url, token, person, needs }`.
- `GET /api/console/caseload`, `/words/{person}`, `/grid/{person}`, `/settings/{person}`,
  `/consent/{person}`; `POST /api/console/words/{person}/{word_id}/approve`.

## Frontend wiring (additive)

- `web/client.js`: new `ServerDriver extends EventTarget` (sibling to `LiveDriver`) that opens
  `/ws`, sends control/text messages, re-emits server events. `window.PLClient.mode()` returns
  `audio` (if `PL_WS_URL`), `server` (if `PL_API`/`?server=1`), else `demo`.
- `web/app.js`: three modes. In `server` mode the demo controls stay visible and map to
  `ServerDriver` methods (WS messages); the real backend decides everything. A small bootstrap
  fetches `/api/session` to obtain the token/ws-url.
- `web/index.html`: wiring comment + bootstrap for `server` mode.
- `web/console.html`: fetch `/api/console/*`, falling back to the existing mock `DATA` when the
  API is absent (so `file://` still works).

## Testing

- `tests/test_app_bridge.py` — pure action↔event / message↔event mapping; presenter.
- `tests/test_app_ws.py` — FastAPI `TestClient`: `GET /`, `/api/session`, token rejection, a full
  Margaret finding-words turn over WS (start→prompt→close match→confirm→yes→found→attempt), the
  stroke-phrase → `safety` path.
- `tests/test_app_console.py` — REST returns seeded data; word-draft approval flips status.
- These need the `api` extra installed; the 103 stdlib core tests stay dependency-free and
  green. `run_tests.py` is unchanged. Audio scaffold is import-guarded.

## Non-goals

- No real ASR/TTS run here (no GPU). The audio transport is scaffolded, not exercised.
- No auth/users beyond the short-lived session token. No PostgreSQL (dev SQLite store).
- No change to the pure core modules or their tests.
