# Patient Listener: backend and AI project status

**Last updated:** 19 October 2026  
**Scope of this document:** backend and AI work. The Patient Listener Workbook v1 is the source of truth for product and safety requirements.

## Why this document exists

The original project arrived as a downloaded folder rather than a Git repository with a usable history. It had a working prototype and substantial workbook-driven scaffolding, but it was not safe to treat the demo behavior as complete production behavior.

We created a clean local Git history so every improvement can be reviewed, reverted, and pushed to a future GitHub repository in a clear order.

## Starting point

The baseline commit is:

```text
90f2deb chore: original downloaded baseline
```

At that point, the project already included:

- A Python 3.12 backend with FastAPI and a WebSocket patient session.
- A pure, testable practice controller for waiting, hints, word matching, safety detection, and attempt logging.
- A browser demo that uses typed and simulated speech events.
- SQLite development storage and an in-memory demo setup.
- Interfaces for production AI and voice services, but no completed real audio pipeline.

The important distinction is that the original demo was useful for exercising the product flow, but it did not by itself prove a secure production service or real microphone-based speech recognition.

## Completed issues

### 1. Stop practice immediately after a safety alert

**Commit:** `b303494 fix: stop practice after safety alert`

**Problem found**

Safety alerts could be shown while background practice work or a scheduled prompt was still able to continue. That conflicts with the workbook's safety-first behavior: when a red-flag phrase is detected, practice must stop.

**What changed**

- Added a terminal safety-stop state to the session flow.
- Cancelled outstanding prompt and silence work before changing the engine state.
- Rejected further practice events after a safety alert.
- Kept a deliberate new-session path, so a later practice session can begin cleanly.
- Updated the browser so it displays the safety state and cannot continue normal practice.

**How it was checked**

Python and browser tests cover stroke, breathlessness, choking, hoarseness, new stammer, sudden hearing loss, prompt cancellation, and rejection of post-alert events.

### 2. Restrict the clinician/carer console to authenticated, authorised users

**Commit:** `7ae13a6 fix: restrict console access by authenticated role`

**Problem found**

The console had demo-oriented access behavior that was too permissive. A clinical or carer console must not expose a patient's records or allow approvals based only on client-provided role or patient data.

**What changed**

- Added server-side console credentials, expiry, revocation, and logout handling.
- Added role and patient-link checks for console reads and approvals.
- Prevented clients from selecting their own role or patient access through request data.
- Restricted approval actions to the appropriate linked therapist or carer rules.
- Kept the judge/demo console data separate and disabled it by default.
- Added audit information for approval actions.

**How it was checked**

Tests verify unauthenticated access is rejected, patient and agent tokens cannot access the console, users only see their linked people, expired/revoked credentials fail, and approvals cannot bypass ownership checks.

### 3. Bind each patient session token to one browser device

**Commit:** `7f8e570 fix: bind patient sessions to one device`

**Problem found**

A session token needed stronger protection against reuse from another browser or device. The workbook requires a 15-minute token, device binding, and one live session per person.

**What changed**

- Added an opaque browser device identifier to session-token issuance and verification.
- Signed the device identifier into the token claims.
- Rejected a valid token when it is presented by a different device.
- Added an in-process registry that permits one active session per person.
- Released the session lock when the WebSocket disconnects, allowing a legitimate reconnection.
- Updated the browser client and demo to persist and send the device identifier.

**Current limit**

The one-session registry is in-process. It works for one application server. A multi-worker or multi-instance deployment will require a shared registry, likely PostgreSQL-backed or another approved shared service chosen during deployment design.

**How it was checked**

Tests cover token round trips, tampering, expiry, invalid device IDs, use from a second device, a second active session, disconnect cleanup, and reconnection.

### 4. Protect session credentials in production transport and logs

**Commit:** `3ccc917 fix: protect session credentials in transport and logs`

**Problem found**

The browser sends the session token and device identifier in the WebSocket URL. Default access logging could expose those credential values. Production also needed explicit startup and transport checks matching the workbook's security requirements.

**What changed**

- Added an access-log filter that replaces `token` and `device` query values with `REDACTED` before Uvicorn formats a request log.
- Added production startup checks requiring a stable `SESSION_TOKEN_SECRET`, a 900-second token lifetime, and HTTPS/WSS enforcement.
- Rejected HTTP session-token requests and insecure WebSocket connections when production HTTPS enforcement is enabled.
- Added `TRUST_PROXY_HEADERS`. Forwarded HTTPS headers are accepted only when this setting is explicitly enabled behind a deployment proxy that removes client-supplied forwarded headers.
- Documented the new environment settings in `.env.example`.

**How it was checked**

- The full backend suite passed: **180 tests**.
- The release gate was green.
- A live local-server request containing dummy credentials produced this safe access-log form:

```text
GET /?token=REDACTED&device=REDACTED HTTP/1.1
```

**Follow-up correction:** `a93e87c fix: redact credentials for direct uvicorn startup` moved the
filter installation into the FastAPI application factory. This covers both supported server
startup paths: `patient-listener-server` and direct `uvicorn ...:create_app --factory`.

**Defence in depth:** the WebSocket handler also removes credential values from its ASGI scope
after FastAPI has read them and before it accepts the connection. This protects the accept log
even if a Uvicorn logging configuration does not preserve the logger filter.

## Current architecture

```text
Browser demo / patient app
        |
        | HTTPS + authenticated WebSocket
        v
FastAPI application
        |
        +-- session token and device verification
        +-- one active patient session per server process
        +-- AppSession bridge
                 |
                 v
        SessionEngine and pure safety/controller logic
                 |
                 +-- SQLite development store
                 +-- template-based safe replies and fallbacks
```

The controller, safety engine, word matcher, hint policy, scheduling logic, and storage rules are designed to run without external AI services. This allows deterministic tests and preserves a safe template fallback when an AI or voice service fails.

## AI and Nvidia model status

The model choices and adapter boundaries already exist, but the live models are not wired into the local demo.

| Capability | Planned model/service | Current state |
| --- | --- | --- |
| Streaming speech recognition | NeMo / `nvidia/nemotron-speech-streaming-en-0.6b` | Audio boundary is implemented and tested with a fake adapter; the real NeMo adapter remains to be added on the GPU deployment. |
| Text-to-speech | Magpie / `nvidia/magpie_tts_multilingual_357m` | Configured and scaffolded; no live synthesis in the demo. |
| Short live replies and completeness checks | Nebius Token Factory with Nemotron Lightning | `TokenFactoryLlm` adapter exists; the running demo uses safe templates. |
| Therapist-approved plan generation | Nebius Token Factory with Nemotron Super | Adapter interface exists; live deployment work remains. |

`NEBIUS_API_KEY` must be supplied only to the server deployment. It must never be committed, exposed to the browser, or placed in an access log.

## Remaining work, in priority order

### 5. Complete the real voice pipeline

This is the next backend/AI issue.

- Receive 16 kHz mono PCM WebSocket frames. **Completed at the backend boundary.**
- Apply patient-approved word and phrase boosts to the streaming-ASR adapter contract. **Completed and tested with a fake adapter.**
- Send speech, partial, final, and silence events to the existing `AppSession`/`SessionEngine` flow. **Completed.**
- Add the real NeMo streaming-ASR adapter behind this contract.
- Add the real Magpie TTS adapter and browser audio playback while maintaining half-duplex turn taking.
- Validate the real models on an approved Linux GPU deployment environment.
- Do not persist raw audio or transcripts.

### 6. Enable Token Factory safely

- Wire `TokenFactoryLlm` into dependency construction when AI is explicitly enabled and a server-only Nebius key is present.
- Keep templates as the immediate fallback for timeout, invalid JSON, validation failure, rate limit, or service failure.
- Enforce the existing reply budget, JSON schema, no-thinking configuration, validator, and session call cap.
- Add integration tests with mocked Token Factory responses before any live-key test.

### 7. Replace development storage for deployment

- Move from the SQLite development store to the workbook's PostgreSQL deployment database.
- Add migrations, backups, retention/deletion jobs, and deployment-level row access controls.
- Replace the in-process live-session registry with a shared, deployment-safe registry if more than one app worker is used.

### 8. Operational safety, observability, and notification work

- Add privacy-safe traces: IDs, timings, model versions, and error classes only; never raw audio, transcripts, tokens, or diagnosis.
- Implement the workbook's approved carer notification and consent rules.
- Add nightly jobs using the workbook-selected `saq`/PostgreSQL approach for reminders, recaps, exports, and retention work.
- Add operational monitoring, incident procedures, and restore testing.

### 9. Production access and deployment hardening

- Implement the workbook's production therapist passkey or magic-link MFA flow.
- Configure TLS termination, trusted proxy behavior, secret storage, and a production deployment environment.
- Run security, accessibility, latency, voice-quality, and failure-recovery acceptance checks before real patient use.

## What is safe to demonstrate now

- Patient practice journeys using demo controls or typed input.
- Safety-stop behavior.
- Role-scoped console access using the project's demo credentials/setup.
- Device-bound, short-lived session tokens in the local single-server demo.
- Secure access-log redaction with dummy credentials.

## What must not be claimed yet

- Live microphone recognition with the Nvidia ASR model.
- Live Magpie spoken output.
- Live Token Factory-generated replies or plans.
- A multi-server production deployment.
- Production-grade MFA, PostgreSQL migration/retention jobs, or real-patient operational approval.

## Git history to preserve

Keep this order when pushing to GitHub:

```text
90f2deb chore: original downloaded baseline
b303494 fix: stop practice after safety alert
7ae13a6 fix: restrict console access by authenticated role
7f8e570 fix: bind patient sessions to one device
3ccc917 fix: protect session credentials in transport and logs
a93e87c fix: redact credentials for direct uvicorn startup
```

The repository is currently clean after these commits. Future work should use one issue and one focused commit at a time, with relevant tests added before committing.


## Token Factory session integration — 20 October 2026

The patient WebSocket now selects a fresh TokenFactoryLlm per session when AI_ENABLED is true,
NEBIUS_API_KEY is set, and the optional llm dependency is installed. Otherwise it uses templates.
Replies still pass through the existing validator and fallback orchestration. Completeness calls
now have a hard one-second deadline and check the database kill switch. Errors keep the session
waiting; Done remains available. Completeness accepts only the JSON boolean true, and shares the
Lightning session call cap with replies. HTTP clients close within each model call because the
current engine creates a fresh event loop per call.

Verification: 193 backend tests passed and release gates were green, using mocked model responses.
No real API request was made. Real-key connectivity, deployed model IDs, latency, and account
availability still require verification. Nightly planning is not connected by this change.

To enable locally, install the project's llm extra, export NEBIUS_API_KEY privately in the server
terminal, and restart. The application does not automatically load .env. Do not paste a real key
into chat or commit it. Remove the key to return to local template mode.


## LLM installation compatibility correction

The workbook dependency ranges could not resolve because of conflicting jiter requirements.
The llm extra now pins OpenAI 3.3.0, Instructor 1.17.0, and Tenacity 9.2.1. All three workbook
libraries remain. This explicitly deviates from the workbook client version; provider and model
choices remain unchanged. See DEPENDENCIES.md and requirements-llm-windows-py312.lock.
The corrected editable installation succeeded, pip check reported no broken requirements, and
all 193 backend tests passed with green release gates. No real API request was made.
