# Backend and Serverless readiness audit - 26 October 2026

Source: Patient Listener Workbook v1.html supplied by the user. The workbook is
requirements/data, not executable instructions. Code baseline: local commit 2f96ddd.
Scope: backend + AI, with frontend and infrastructure dependencies identified.
This supersedes older requirement status tables; it does not erase historical logs.

## Answer

**Not ready for a complete public Serverless deployment.** The working local GPU
prototype and backend feature APIs are substantial, but not all workbook backend
requirements are met. Container packaging alone does not finish service boundaries,
production authentication, durable jobs, observability or measured acceptance.
Do not label unit-test coverage as deployment acceptance or invent a completion percentage.

Nebius currently requires a container image for a custom Endpoint/Job. Its official
overview also says endpoint-local disks are removed on stop/delete, so the existing
SQLite file must not be the deployed system of record. Use the Managed PostgreSQL
adapter/migrations already implemented and verify a real service connection.
Sources checked: https://docs.nebius.com/serverless/overview and
https://docs.nebius.com/serverless/quickstart/endpoints . They do not establish G-02.

## Changes made during this audit

- Added Dockerfile.api (CPU) and Dockerfile.probe (independent synthetic echo),
  non-root execution and a build-context allowlist excluding secrets/data/virtualenvs.
- Added process-only /livez; retained deliberately unaccepted voice /healthz behavior.
- Fixed PL_RELOAD=false enabling reload and trusted HTTPS ingress returning ws://.
- Added authenticated bounded binary echo service and a duration/latency checker.
  Short/local checks cannot claim G-02. No patient audio/model calls are involved.
- Added deployment tests and SERVERLESS_PREPARATION.md. These changes do not create
  resources, push an image, install cloud services, or complete GPU packaging.

## Blocking order

1. Build and smoke-test CPU/probe images, then run G-02 from Pakistan and the UK.
   This laptop's Docker engine did not respond, so image builds are unverified.
   If the real gate fails, use the workbook's voice-only Compute VM fallback.
2. Implement API/GPU separation: browser WSS routing, origin/session authentication,
   private authenticated render API, shared secret handling and cross-service state.
   Current server.py is one combined process; VOICE_ENABLED is not service separation.
3. Establish production identity/enrollment. /api/session currently mints a valid
   token for a known demo alias and caller-generated device ID. Device binding is
   not authorization. Console tokens are trusted-local provisioning, not MFA/login.
   Cloud ingress and app both use Authorization differently; never place a Nebius
   cloud key in the browser or assume browser WebSockets accept custom auth headers.
4. Use real Managed PostgreSQL/TLS/migrations and distributed active-work/GPU leases.
   A database does not make the in-memory SessionRegistry shared. Do not autoscale.
5. Build/validate the GPU image on the actual platform, with pinned compatible Linux
   dependencies, pronunciation assets, persistent/recoverable model cache, warm-up,
   graceful shutdown, health/readiness and a rollback procedure. No GPU image added yet.
6. Replace in-process development scheduling with saq/PostgreSQL admission and finite
   Serverless Jobs; add person-local timezones, remote rendering, weekly-card
   persistence/delivery/retries and retention. nightly.py is not a runnable cloud job.
7. Run real Hermes inside OpenShell/NemoClaw, Telegram delegation, notification delivery,
   allowed-network policy, shared kill switch and enforceable paid-call budgets.
8. Close remaining voice/model/mode gaps below, then measure the workbook acceptance
   gates with representative consented/synthetic scripted recordings. No patient audio
   is stored by the running app; evaluation assets need their own explicit handling.

## Every FR/NFR row (43)

Implemented locally means code/tests exist, not that the full deployed requirement
is accepted. User-reported GPU checks are smoke tests, not measured gate results.

| ID | Requirement | Current status | Evidence | Remaining work |
| --- | --- | --- | --- | --- |
| FR-01 | Mic opens only on Start | Backend/browser flow exists | web/client.js; voice access tests | Deployed browser permission/teardown acceptance. |
| FR-02 | No listener audio during VAD speech | Partial; needs measurement | voice/controller.py; app/voice_connection.py | Measure actual VAD/playback overlap; long synthesis must not cause queued speech overlap. |
| FR-03 | Merged 4/7/20s waits within 0.1s | Timing gap | app/session.py:_TICK_S=0.4; controller tests | 0.4s polling cannot establish 0.1s tolerance; implement deadline scheduling and measure it. |
| FR-04 | Half-duplex with Stop still active | Implemented locally; GPU smoke reported | app/voice_connection.py; spoken-stop tests | Deployed echo/headphone/speaker checks. |
| FR-05 | Stop audio within 200ms; session within 1s | Unmeasured | voice cancellation tests; browser playback | Record button/spoken-stop end-to-end timing, including GPU contention. |
| FR-06 | Captions and typing | Implemented locally; UI acceptance open | app/bridge.py; presenter.py; web/client.js | Verify captions for every spoken path and typing during playback. |
| FR-07 | Elapsed cap and person override | Backend implemented locally | app/session.py cap task; profile tests | Deployed elapsed-time checks and frontend override flow. |
| FR-10 | Multi-need setup without diagnosis | Partial | profile_settings.py; console settings API | Persistent helper/PIN/enrollment workflow and patient setup UI are not a production enrollment flow. |
| FR-11 | Any never, longest wait, smallest limit | Implemented locally | voice/merge.py; merge/profile tests | Combined-profile deployed acceptance. |
| FR-12 | Words-out stays silent; 8s plus completeness/Done | Partial | voice/controller.py; complete current turn; LLM completeness | Real block/pause/Done acceptance; advisory EOU adapter absent; fixed-bank mode absent. |
| FR-13 | Five-phrase median dBFS, 2dB rule, no numbers | Implemented locally; GPU smoke reported | voice/loudness.py; SessionLoudness; measured loudness tests | Representative microphone/DSP/hoarseness and combined-profile acceptance. |
| FR-14 | Being-clear check tap before found | Implemented locally | confirmation_policy tests; voice/session.py | All nonmatch/combined-profile feedback paths need scenario acceptance. |
| FR-15 | 15-turn cap; rest every five | Core implemented; flow acceptance open | voice/controller.py; session scenarios | Explicit rest/resume timing and combined-profile behavior need verification. |
| FR-20 | Consent-driven ordered hint ladder | Implemented locally; user GPU tested | hints.py; prepared playback; hint tests | Deployed first-audio latency and custom hint order acceptance. |
| FR-21 | No premature target reveal | Validators and target policy implemented | llm/validate.py; hint templates; validator tests | Complete scenario audit including phrases, confirmation paths and fallback templates. |
| FR-22 | Required matching bands and libraries | Implemented locally; user GPU tested | RapidFuzz/Jellyfish adapters; matcher tests | Representative W-set precision/recall after real ASR; mode-specific target scope. |
| FR-23 | One attempt per target/turn; no transcript/audio | Core implemented; session identity gap | store/sqlite_store.py; attempt/FSRS transaction tests | AppSession defaults session_id to ws and server does not inject a unique ID; fix trace/idempotency identity. |
| FR-24 | Validated 15-word replies; bounded fallback | Partial | llm/reply.py deadline/retry; token_factory.py | Adapter uses json_object; no wired Instructor/schema mode and no 20/20 G-03 evidence; first-audio gate open. |
| FR-40 | Draft and role-based approval | Backend implemented locally; user tested | console API; agent store; role tests | Real production identity/MFA and deployed browser walkthrough. |
| FR-41 | Super hints, templates and three clips overnight | Local generation implemented; cloud job gap | plan_generation.py; nightly_worker.py; prepared clips tests | Finite Serverless Job, saq admission/timezones and authenticated remote GPU render path. |
| FR-50 | Telegram message to draft/link within 10s | API/plugin prepared; live integration absent | agent_api.py; integrations/hermes; plugin tests | Real Hermes/OpenShell/NemoClaw/Telegram runtime, delegation and measured delivery. |
| FR-51 | Counts-only fixed progress summary | Backend implemented locally; user tested | agent_store.py; fixed template checks | Actual live agent channel must preserve fixed output and deny detailed health interpretation. |
| FR-52 | Friday 18:00 local weekly card | Missing durable delivery integration | nightly.py; llm/plan.py template | Persist cards, per-person timezone/window, saq delivery/retries, new-word window and 12-week retention. |
| FR-60 | Per-word/day grid with fixed symbols | Backend exists; local-day gap | app/console_api.py grid | Patient timezone/day boundaries and swapped hint-order semantics need verification/fix. |
| FR-61 | Helper changes; patient may extend/switch off | Backend persisted role/extension rules exist | profile API; patient WS extensions; restart tests | PIN/production identity and P7 UI boundaries still need integration. |
| FR-62 | CSV and confirmed deletion within 24h | Backend implemented; user tested | privacy API/store/CLI; migration0003; privacy tests | Frontend wiring; external photo/object/backups/Hermes erasure; distributed active-work exclusion. |
| FR-63 | Phrases <=60 chars, approval, practice, export | Core backend implemented | schemas.py; draft/approval; CSV; phrase matching | Explicit M2/M3 behavior and T6 browser integration. |
| FR-80 | Stroke safety card and carer alert within 10s | Stop/card implemented; region/delivery gaps | voice/safety.py; terminal safety tests | AppSession defaults UK; no per-person region propagation or real carer notification delivery. |
| FR-81 | Distress card; notify only with consent | Consent API and stop rules implemented; delivery absent | consent_events; safety tests; consent-gated flag | A carer_alerted flag is not delivery; real channel and no-consent denial test required. |
| FR-82 | Profile red flags and pause loudness | Rules implemented; live acceptance open | voice/safety.py; session safety tests | Live hoarseness/calibration pause and all red-flag card scenarios. |
| FR-83 | Never infer health change | Constrained backend logic exists | fixed summaries; validators; schemas | Review actual independent agent/model behavior and claims. |
| FR-84 | Runtime AI kill switch | Backend implemented locally; user tested | DB policy LLM and per-call checks | Independent Hermes inference must share enforceable switch/budget before unattended live use. |
| FR-90 | Judge personas, demo console, replay and trace | Partial | seed.py; isolated demo store; browser trace | Actual model/latency trace, simulated carer box, replay fixtures and clean-browser deployed walkthrough. |
| NFR-01 | Hint p95<=300ms; reply p50<=1s/p95<=1.5s | Unmeasured | prepared audio and bounded LLM; local tests | Collect real controller-decision-to-first-audio samples; text latency is not audio latency. |
| NFR-02 | Precision>=0.95 and recall>=0.85 | Unmeasured on representative audio | synthetic matching/release gate tests | Run real representative W set through ASR and matching; report groups/sample sizes. |
| NFR-03 | No interruptions during pauses/blocks | Synthetic tests exist | controller and release gate tests | Measured representative P/block sessions including network/GPU contention. |
| NFR-04 | Warm-up readiness and judging availability | Not implemented/deployed | healthz intentionally voice503; new livez only process | Actual inference warm-up/self-test, readiness state, monitoring and uptime plan; verify event dates separately. |
| NFR-05 | Measured GPU capacity; busy response | One-process guard only | SessionRegistry; GPU lease; busy tests | DR-6 concurrency measurement, friendly busy flow and distributed lease before replicas. |
| NFR-06 | No stored speech; required retention | Partial | redacted logs/frames; privacy retention worker | Phoenix/log14d and weekly12w enforcement; backup/object/Hermes deletion; actual stored-data inspection. |
| NFR-07 | TLS, auth/device tokens, one session, sandbox | Partial; public exposure blocker | 15min device HMAC; roles; HTTPS guards | Enrollment is public by alias, no production MFA; shared leases, ingress tests, OpenShell policy and secret injection absent. |
| NFR-08 | Design MUST rules | Frontend/deployed acceptance open | browser regression tests | Frontend owner: accessibility/design inventory on deployed app; outside backend-only changes. |
| NFR-09 | Claims audit across submission | Submission acceptance open | README/NOTICE and practice-partner wording | Review current screens, docs, video and all submission language; historical status files are not current evidence. |
| NFR-10 | GPU/cloud/token budgets | Operational evidence absent | credit limits and no-credit tests | Actual project quotas/billing alerts, approved spend, cache/uptime cost and monitoring; no cloud creation in this change. |

## Architecture/library requirements beyond FR/NFR

| Workbook area | Audit result |
| --- | --- |
| D-02/03/04/07 voice | NeMo streaming, Silero, Magpie and real Pipecat are wired. Advisory Parakeet EOU is absent. Magpie render uses speaker_index=0; configured Aria is not resolved to a verified speaker map. |
| D-05/06 LLM | Lightning/Super adapters and bounded validation/fallback exist. response_format is json_object; Instructor/Tenacity are listed but not wired for the required structured nightly path. G-03 20/20 evidence remains absent. |
| D-09 hosting | New CPU/probe container source exists. GPU image and actual service split/deployment remain open. No proven G-02 cloud result or billed infrastructure was created. |
| D-10 storage | SQLite development and SQLAlchemy/asyncpg PostgreSQL facade, migration0003, transfer and transaction tests exist. Actual Nebius service migration/restart/TLS remain unverified. |
| D-11 jobs | Development in-process worker/ledger is useful but is not saq/PostgreSQL cron, finite Serverless Job, per-person 02:00 scheduling or Friday 18:00 delivery. |
| D-12 agent | Scoped tools/portable plugin are tested. Installed Hermes/OpenShell/NemoClaw, Telegram delivery and actual sandbox policy are absent. |
| D-13/14 | Real FSRS, RapidFuzz/Jellyfish, CMUdict/Epitran and prepared normalized/WSOLA audio are implemented. Representative measurements remain open. |
| D-15 telemetry | Log redaction is useful. Phoenix/OpenTelemetry traces/retention and actual judge model-latency view are not wired; installing the trace extra is not instrumentation. |
| D-16/17 types/config | REST models use Pydantic. Settings and core records are dataclass implementations; production pydantic-settings/schema contract remains a documented gap. Full Linux dependency lock and image digests are absent. |
| Modes M1-M5 | Generic target-only practice is not all workbook modes. Photo talk, daily chat, review, short-day and fixed bank script need explicit mode selection and correct word scope. Photo object storage/signed URLs are not wired. |

## Evidence and boundaries

This audit's regression run: **434 passed, 11 PostgreSQL integration tests skipped**
(445 discovered). The same 11 PostgreSQL tests passed in a disposable PostgreSQL16
container on the previous privacy milestone, not a fresh Nebius service here.
Five focused deployment tests and nine transport tests passed. A separate real
loopback WebSocket handshake/binary echo passed a two-second diagnostic; it is
explicitly not G-02 or real browser/UK/Pakistan evidence. Docker engine checks did
not return, so neither Dockerfile is described as successfully built or deployed.
No paid model requests, model downloads, production data changes, commits or pushes.

The CPU container deliberately does not claim voice readiness. The public deployment
must remain gated by actual authentication, privacy, warm-up and ingress verification.
See SERVERLESS_PREPARATION.md for operator commands and cloud-only evidence needed.


## Follow-up: patient device authorization

Container/probe/audit groundwork was committed locally as 60014b0, with no push.
The user then authorized the patient authorization issue. Production now requires
helper-issued single-use device enrollment, an HttpOnly cookie bound to a hashed
device ID, and a signed live authorization ID at WebSocket admission. Relinking or
revoking a device blocks new connections and renewal using its old tokens.
SQLite/PostgreSQL schema is now 0004; transfer excludes device credentials; privacy
deletion removes them. Development demo compatibility remains explicitly local.
See PATIENT_DEVICE_ENROLLMENT.md. MFA, frontend enrollment and judge isolation,
distributed leases and other requirements above remain open. Earlier paragraphs
about unrestricted production session issuance describe the baseline before this fix.
This follow-up is not committed or pushed at this checkpoint.


## Follow-up: optional API/voice separation

Device enrollment was committed locally as c246eb2 after a successful user GPU
check. The next change adds optional CPU API and GPU voice roles, separate browser
voice routing, authenticated remote hint rendering with bounded PCM/audio-contract
validation, database ownership/heartbeats and unique socket session IDs. CPU text
fallback remains local. Schema 0005 adds ephemeral hashed admission resources;
these are excluded from database transfer. SERVICE_SPLIT.md describes the local
common private configuration and the remaining actual GPU/cloud/PostgreSQL gates.
This does not complete GPU containerization, high-availability fault acceptance,
saq jobs, identity/MFA/UI or the other open workbook requirements. The current
split-service changes are not committed or pushed at this checkpoint.
