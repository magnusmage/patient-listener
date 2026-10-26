# Serverless preparation: container groundwork, not deployment acceptance

26 October 2026. See BACKEND_DEPLOYMENT_AUDIT_2026-10-26.md for the full requirement audit.

## Current packaging

- Dockerfile.api packages the current CPU API, store and LLM adapters on Python 3.12.
  It installs CMUdict and the pinned English Flite pronunciation assets at build time,
  copies only the application/static files, and runs as non-root. There is no GPU
  dependency or automatic model call in this image. AI and nightly work default off.
- Dockerfile.probe packages an independent authenticated synthetic echo service.
  It imports no application/store/model modules and cannot access patient records.
- .dockerignore is an allowlist: .env, keys, Git history, virtualenvs, local databases,
  diagnostic reports and model files never enter the build context.
- /livez is process liveness. /healthz retains the existing deliberate 503 for
  unaccepted voice readiness. Do not point a voice readiness gate at /livez and call
  that a warm-up pass. GPU readiness needs real inference and acceptance evidence.
- The application entrypoint binds PL_HOST/PL_PORT, parses PL_RELOAD=false correctly,
  and leaves proxy interpretation to the explicit application trust configuration.
  HTTPS proxy requests now receive wss:// URLs rather than ws:// URLs.

These are CPU/probe Dockerfiles only. A validated GPU image, API/voice separation
and a finite cloud job entrypoint are still required. The app remains a combined
API and voice runtime. VOICE_ENABLED=false on a CPU endpoint does not route browser
voice to another endpoint: routing and authenticated remote rendering need code.

## Local build (Docker engine required)

From the repository root:

```bash
docker build -f Dockerfile.probe -t patient-listener-probe:local .
docker build -f Dockerfile.api -t patient-listener-api:local .
```

Builds use network package/source/corpus downloads but do not call Token Factory
or download NeMo/Magpie weights. Dependencies are resolved against pyproject.toml;
a full Linux constraints/lock file and image digest pinning remain release work.
The Windows LLM lock file is not a Linux deployment lock. Use pip check during build.

A loopback-only CPU smoke run uses a throwaway in-memory store:

```bash
docker run --rm --name patient-listener-api-check -p 127.0.0.1:18000:8000 patient-listener-api:local
```

Check http://127.0.0.1:18000/livez and /healthz. This is a local text/API check,
not a public production configuration and not a voice endpoint. Device enrollment
is required by default in this CPU image; an unlinked session request should be HTTP401. Do not attach
production credentials or use its default in-memory store for actual records.

## G-02 echo probe before GPU provisioning

Run Dockerfile.probe on a CPU endpoint first, with PL_PROBE_TOKEN set privately to
a new random token (32..256 printable ASCII characters). Keep this distinct from
Nebius credentials, console tokens and the session-signing secret. Expose only
container port 8000 via the managed HTTPS interface. Keep access logs disabled for
the probe. Send only synthetic bytes, never microphone audio or patient words.

The probe uses the Authorization header. Check how endpoint authentication forwards
or consumes that header; matching ingress/probe credentials can be used for this
disposable test only if verified. A successful Python client does not establish
browser authentication compatibility: browser WebSockets cannot set an arbitrary
Authorization header. The final gateway/ingress must reconcile cloud authentication,
console bearer tokens and device/session tokens without exposing cloud credentials.

With the API dependencies installed, run from Pakistan and separately from the UK:

```bash
python -m patient_listener.tools.websocket_check --url wss://YOUR_MANAGED_HOST/echo --location Pakistan --out g02-pakistan.json
python -m patient_listener.tools.websocket_check --url wss://YOUR_MANAGED_HOST/echo --location UK --out g02-uk.json
```

Each command prompts privately for the disposable probe token and defaults to a
continuous 600-second connection. It sends one small random binary echo per second,
records p50/p95/max round-trip timings, rejects redirects, and stores no URL/token
or audio in its report. G-02 requires both locations to pass, with all measured
round trips below 200 ms. A short --seconds 2 local check is explicitly not a gate
pass, and a local report can never pass the regional gate. Stop/delete the test
endpoint after collecting evidence. These commands do not create cloud resources.
If G-02 fails, record the workbook's GPU Compute VM fallback, keeping API/job Serverless.
Also test the actual browser socket route after the final authentication layout exists.

## Production configuration gates

1. Use a migrated PostgreSQL DATABASE_URL, schema 0005, with verified TLS. Do not
   rely on endpoint-local SQLite: endpoint disks are removed on stop/delete.
   Remove PL_DB_PATH and run tools.database upgrade as an operator migration step,
   not concurrently from every replica. Database backups and deletion retention
   require an operational policy. Keep keys injected at runtime, never in images.
2. Set PL_ENV=production, REQUIRE_HTTPS=true, a stable private SESSION_TOKEN_SECRET,
   SESSION_TOKEN_TTL_S=900, and PL_RELOAD=false. Configure TRUST_PROXY_HEADERS=true
   only if ingress removes forged forwarded headers and direct container access is
   blocked. Patient enrollment is now mandatory in production; wire the one-time
   setup flow documented in PATIENT_DEVICE_ENROLLMENT.md before patient use.
   Keep the browser on a verified HTTPS origin; TLS/proxy behavior needs
   an actual ingress test. No built-in production identity provider exists yet.
3. Keep one process/replica and no autoscaling until distributed session/GPU leases
   and deletion/generation coordination are implemented. Separate endpoints with
   independent in-memory registries do not enforce one live session per person.
4. Keep NIGHTLY_ENABLED=false for cloud endpoints until saq/PostgreSQL scheduling,
   per-person timezones, finite Jobs and remote authenticated rendering exist.
   The current scheduler is a development task tied to one API process.
5. Keep AI disabled for initial network checks. The saved DB AI switch controls
   backend inference; an independent Hermes provider is not covered by that switch.
   Approved credit budgets and per-service monitoring are still required.
6. Establish GPU model/cache mounting, warm-up, graceful termination, external
   photo/clip storage deletion, observability and secrets/proxy boundaries before
   public availability. Do not claim installing a model means acceptance passed.

## Current documentation checked

- https://docs.nebius.com/serverless/overview : containers are required; Jobs are
  finite and Endpoints serve requests. Endpoint-local disks are removed on stop/delete.
  Running endpoints are billed while running; do not assume billing stops when idle.
- https://docs.nebius.com/serverless/quickstart/endpoints : declared HTTP ports
  receive managed HTTPS URLs and endpoint authentication has its own token.

Availability, quotas, networking and websocket behavior must be checked in the
actual project. This change creates no cloud resources, pushes no image/code,
changes no production records and makes no paid model calls.


## Service-split follow-up

The optional api/voice roles, authenticated remote rendering and database admission
are now implemented; see SERVICE_SPLIT.md. The original paragraph describing an
unsplit server is the baseline before this change. Schema is now 0005. The GPU
container and actual cloud gates remain open; combined mode is still available.
