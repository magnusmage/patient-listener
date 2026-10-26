# CPU API / GPU voice split - 26 October 2026

## Status and boundaries

Enrollment was committed locally as c246eb2 after the user's GPU check passed.
This change adds executable api and voice roles alongside the existing combined
mode. It creates no cloud resources and does not claim all workbook acceptance
requirements are met. The GPU image, real PostgreSQL gate and deployed WSS/latency
checks remain necessary before Nebius rollout.

| Role | Responsibilities | Excluded |
| --- | --- | --- |
| combined | Existing single-server development workflow | No new separation assumed |
| api | Static frontend, console/agent APIs, enrollment, short-lived tokens, text WebSocket, plan validation/publication | No GPU models or private renderer |
| voice | Authenticated live voice WebSocket and private hint renderer, GPU model lifetime | No frontend, helper/agent APIs, enrollment or token issuance |

Both split roles require one shared persistent database and the same stable
SESSION_TOKEN_SECRET and VOICE_SERVICE_SECRET. These two secrets must differ.
Production requires PostgreSQL with verified TLS. Development may use one absolute
SQLite path on the same host; do not copy SQLite files between hosts and call them
shared storage. In-memory databases are refused for split roles. Enrollment is
mandatory for both split roles, including development.

## Browser and rendering contracts

The microphone driver requests /api/session?person=...&voice=true from its same-origin
CPU API; the response supplies the configured GPU ws_url. The browser uses its
short-lived, signed, device/authorization-bound token at that GPU URL. Only exact
configured VOICE_ALLOWED_ORIGINS are accepted on the GPU WebSocket. No cloud key
or private service secret goes into browser code. Regular text requests keep the
CPU WebSocket URL so text fallback does not depend on GPU availability. The only
frontend change is the transport-selection query in the existing driver, not UI.

CPU plan generation calls /internal/render on VOICE_INTERNAL_URL with a distinct
X-PL-Service-Key plus proof of its live person-admission lease. The GPU verifies
that proof, person existence, matching audio contract and exclusive GPU capacity.
The response is bounded mono PCM16 little-endian at 22050Hz, with a fingerprint of
the model/voice/normalization/stretch settings. Mismatches, oversize/odd PCM, missing
keys, stale admission and redirects fail closed. There are no HTTP retries and
no credentials in query strings. Remote transport ignores ambient proxy settings
and verifies HTTPS certificates. Cleartext URLs are allowed only on loopback in
development. The render route must also be restricted by cloud private networking;
application authentication does not replace ingress/network policy.

## Shared admission

Schema 0005 adds session_leases. One owner may hold a person resource, and only one
GPU resource is admitted globally until actual capacity is measured. Resource IDs
are hashed, ownership tokens are random, and database time governs 90-second expiry.
Owners renew every ten seconds on a dedicated connection. Renewal loss cancels
the owning operation; rendering/publication recheck admission. A stale owner cannot
renew or release its successor. Dead-worker rows expire; stale rows are removed by
maintenance. Transfer to a new database excludes these ephemeral credentials.

Deletion/export/plan generation and practice share the same person guard across
split processes. GPU work keeps its capacity slot until outstanding worker calls
finish on cancellation, preserving the existing no-late-output behavior. The local
combined SQLite demo keeps its existing in-process registry; PostgreSQL combined
mode uses shared ownership. New sockets get unique session IDs rather than ws.

This is conservative admission, not a proven high-availability system. Cloud fault
injection, database outages, VM suspension longer than TTL, process restarts and
GPU stalls still require deployment acceptance. Do not increase replicas or claimed
GPU capacity until those checks and DR-6 pass. The lease keeper uses database time
and cancels on loss; fencing arbitrary external side effects is outside this build.

## Local GPU setup: one private config, two terminals

Copy this update's files into ~/patient-listener-voice/project, preserving .env,
pl.db/WAL, the parent virtualenv, model cache and your diagnostic report. Stop the
old combined server before using its port. No new Python dependency is required.
SQLite creates schema 0005 on open. For PostgreSQL, upgrade before starting workers:

```bash
python -m patient_listener.tools.database upgrade
```

Create the private common configuration ONCE:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m patient_listener.tools.services init --db pl.db
python -m patient_listener.tools.services check api
python -m patient_listener.tools.services check voice
```

This writes .env.split with file permissions 0600, existing absolute database path,
distinct generated secrets, loopback endpoints and enrollment enabled. It does not
change database records. Re-running init refuses to overwrite the file, preventing
accidental key rotation. Never upload/commit/paste this private file. Its basename
is already git-ignored and the Docker build allowlist excludes it.

The launcher rejects any exported variable that conflicts with the shared file;
it names only that variable, never its value. Unset the named variable in the current
terminal and retry. It then forces the requested role, correct VOICE_ENABLED and
nightly off. This prevents the earlier token problem from silently selecting a
different database/key in each terminal. Existing exported variables are never
silently overwritten with secret values. To use nondefault ports, choose init's
--api-port/--voice-port before creating the file.

For credit-free practice/render checks, turn OFF the persisted AI switch explicitly:

```bash
python -m patient_listener.tools.switch --db pl.db --ai-enabled false --reason split-service-check
```

AI_ENABLED=false in a new config is only the initial database default and does not
override an already saved true value. The shared file contains no Nebius model key.
The configuration checker loads no models, connects to no database and spends no
credits. Starting the voice role loads the existing GPU weights and prepares fixed
clips locally, as the combined server did; it does not call Token Factory.

Terminal 1 (GPU voice):

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m patient_listener.tools.services run voice
```

Terminal 2 (CPU API):

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m patient_listener.tools.services run api
```

Defaults are API port8000, GPU port8001. Both terminals must use the SAME project
folder and SAME .env.split. The API has no voice model load. Wait for voice startup
to finish. /livez confirms process liveness only; voice /healthz deliberately remains
503 until measured production readiness is implemented.

## No-credit verification

In another activated terminal:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8001/healthz
python -m patient_listener.tools.patient_access_check --person margaret
```

Health reports service_role and remote_voice_configured, not a claim that the GPU
has passed acceptance. The enrollment checker talks to CPU port8000 and revokes
only its own test device. Use the helper token issued from the SAME pl.db. A valid
existing helper token remains valid; neither launcher creates/revokes Sam's token.

To verify actual GPU rendering THROUGH the CPU, use:

```bash
python -m patient_listener.tools.generate_plan --person margaret --max-words 4
```

This replaces Margaret's saved practice plan using approved words, templates and
remote GPU clips. It changes the plan intentionally; it is not a read-only check.
There are no Super calls without --use-ai. Confirm model_attempts=0 and rendered
clips for the selected words, then inspect both servers' sanitized logs.

Browser voice also needs a valid enrolled browser; the one-time setup UI is still
frontend work. A helper can exercise the documented enrollment API manually for
a development test. The diagnostic CLI's test cookie is in memory and cannot enroll
your browser. Do not interpret its success as completion of the browser UI.
Use the CPU page with ?voice=1. If viewing from another computer, 127.0.0.1 means
THAT browser's computer: forward both ports or configure real HTTPS/WSS origins.
Never substitute a cleartext public address or wildcard origin to bypass validation.

## Nebius configuration and open work

Set PL_SERVICE_ROLE=api / voice explicitly in deployment environments. CPU image
still defaults to combined for its loopback-only packaging check; it does not
load models. The GPU role needs the existing NeMo/PyTorch stack and a validated
GPU container, not Dockerfile.api. Set actual VOICE_PUBLIC_WS_URL (wss URL ending
/ws), VOICE_INTERNAL_URL (private HTTPS origin), exact browser origins, PostgreSQL
URL, distinct injected secrets and identical audio settings on both services.
Do not place these secrets in images, URLs, browser globals or public repositories.
Resolve managed endpoint auth headers versus application/service tokens before
opening ingress. G-02 from Pakistan+UK remains unpassed by the local echo check.

Finite Serverless Jobs/saq, Hermes notifications, frontend setup/MFA, regional/mode
requirements, Phoenix, verified voice selection, warm-up/uptime and representative
acceptance measurements remain separate tasks. This service boundary is not a
completion claim for those requirements or for all of NFR-07.


## Verification for this change

460 backend tests passed; 14 opt-in PostgreSQL integration tests were skipped
(474 discovered). All 24 browser checks passed. Eleven focused split/config/lease
checks include two independent apps sharing a temporary database and a real HTTP
rendering round trip with synthetic PCM. A clean CPU subprocess imported neither
PyTorch nor NeMo. These tests do not perform NVIDIA inference or paid calls.
The GPU service does not seed people or create a judge-demo store at startup.
The user verified both roles on the local GPU machine: browser enrollment and
session issuance succeeded, and transcription, spoken replies, hint playback and
Stop passed. The API reported no models loaded; the voice service reported models
loaded with Pipecat. Actual prepared-plan generation through the private renderer,
PostgreSQL migration0005 and cloud/fault acceptance remain required.
The split milestone is being committed locally; no remote push is authorized.
