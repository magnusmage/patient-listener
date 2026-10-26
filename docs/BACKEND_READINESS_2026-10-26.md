# Backend readiness against the workbook - 26 October 2026

## Release verdict

NOT COMPLETE. This is a current audit of the actual code against the supplied
Patient Listener Workbook v1.html, not a declaration that all MUSTs pass.
The workbook remains authoritative; general hackathon eligibility is less strict
than the workbook's deployment requirements. Cloud credentials alone will not close
remaining implementation, frontend, integration and measurement gaps.

Baseline: b48578c locally committed GPU container milestone. A subsequent local checkpoint commit was requested after this audit; no remote
push is authorized. The user's token-factory-check.json is
excluded from all update packages. Synthetic tests use no patient audio or paid API.

## Fixes made during this audit

1. FR-03: replace 400ms silence polling with pure controller deadlines. Fake-clock
   tests cover 4/7/20s, <=80ms synthetic scheduling jitter without accumulated drift,
   disabled waits, speech cancellation, Words-out and merged profiles. This fixes
   deterministic scheduler granularity; real VAD/audio timing still needs measurement.
2. NFR-04: startup now exercises Silero, NeMo streaming decode and phrase-boosting
   kernels with generated silence, validates all ten prepared PCM16 fixed clips,
   and synchronizes CUDA. Any failure prevents startup. No text model calls or
   microphone input. /healthz reports voice_ready/200 only after this warm-up and
   the expected Pipecat version; weights alone remain 503. Liveness remains /livez.
   production_acceptance_verified stays false; readiness is not the release gate.
3. FR-15: automatic rest resumes its already reserved target without consuming an
   extra turn or skipping it. Manual rest cancels silence/advance timers and pending
   playback. Practice inputs are ignored while resting; safety, Stop and elapsed
   session caps remain active. Tests require exactly 15 prompts and two rests.

## Every functional requirement

Implemented locally means code and synthetic checks, not deployed acceptance.
Frontend acceptance and actual external delivery must not be counted as backend code.

| Requirement | Current backend position | Still required |
|---|---|---|
| FR-01 | Start-gated mic transport exists | Browser/deployed permission and teardown acceptance |
| FR-02 | Controller speech priority and bounded half-duplex pipeline | Representative VAD/playback overlap measurement |
| FR-03 | Deadline scheduler added in this audit | Actual VAD-to-controller and output timings within +/-100ms |
| FR-04 | Playback capture limited to Stop/safety handling | Speaker/echo/headphone acceptance |
| FR-05 | Stop/cancellation paths and late-output suppression tested | Trace actual <200ms audio and <1s session stop |
| FR-06 | Captions and typed controls exist | Every spoken path, browser playback and typing acceptance |
| FR-07 | Persisted elapsed cap and extension/off rules | Deployed timer/override acceptance |
| FR-10 | Needs schema and helper settings API | Production setup identity/PIN and frontend flow |
| FR-11 | Merged-profile rules tested | Representative combined-profile acceptance |
| FR-12 | Silent Words-out, 8s completeness/Done and timeout fallback | Advisory Parakeet EOU adapter; live block scenarios |
| FR-13 | Five-phrase median dBFS, 2dB rule and microphone metadata | Real microphones/DSP/hoarseness acceptance |
| FR-14 | Check tap required before found for Being-clear | All combined-profile browser scenarios |
| FR-15 | Rest/resume and 15-turn accounting corrected | GPU/browser rest acceptance; elapsed cap remains active |
| FR-20 | Consent-driven ordered hints and cached audio | All hint orders and actual first-audio latency |
| FR-21 | Text validators and target-reveal rules | Complete phrase/confirmation/fallback reveal scenario audit |
| FR-22 | Required matching libraries and score bands | Representative audio precision/recall; G-04 fallback decision |
| FR-23 | Atomic attempts/FSRS and unique socket IDs | Deployed concurrency/idempotency/schema review |
| FR-24 | Validation, retry budget and strict 1.5s fallback | Reliable live latency, structured-schema/Instructor integration and G-03 evidence |
| FR-40 | Draft/approval roles enforced; agent cannot approve | Production identity/MFA and frontend walkthrough |
| FR-41 | Super/template plan generation and remote GPU clips work | Durable per-person saq/Serverless nightly execution |
| FR-50 | Scoped agent draft API/plugin and idempotency tested | Real Hermes v0.19.0 + sandbox + Telegram; draft/link <10s |
| FR-51 | Fixed counts-only summary backend tested | Real agent output preserved verbatim; no interpretation |
| FR-52 | Weekly card construction exists | Durable cards, new-word window, person timezone, Friday18:00 delivery/retries |
| FR-60 | Grid API exists | Person-local dates and hint-order symbol semantics |
| FR-61 | Helper authorization and patient extend/off rules | Production PIN/identity and frontend boundaries |
| FR-62 | Authenticated CSV, confirmation/receipt deletion and tombstones | External photo/object/backups/Hermes erasure; frontend wiring |
| FR-63 | <=60-character phrases, approval and CSV | Explicit M2/M3 phrase practice and frontend round-trip |
| FR-80 | Safety detection/card/session stop exist | Person region/local number propagation and real carer delivery <10s |
| FR-81 | Distress rules and consent-gated notification flag | Actual consent-gated notification delivery |
| FR-82 | Red-flag rules and hoarseness handling tested | Live profile scenarios and notification path |
| FR-83 | Counts-only logic and no health-inference path | Independent Hermes behavior and complete claims review |
| FR-84 | Persisted kill switch rechecked per backend model call | Hermes inference must share enforceable switch and budget |
| FR-90 | Three demo people and isolated demo console exist | Isolated judge voice flow, replay, simulated carer and real model/timing trace view |

## Non-functional release blockers

| Requirement | Position and remaining acceptance |
|---|---|
| NFR-01 latency | Single synthetic live pipeline reply passed at1.048s; other Lightning request2.977s and browser calls timed out. This is not p50/p95 first audio. Fix avoidable overhead without relaxing1.5s; measure cached hints and synthesized replies. |
| NFR-02 accuracy | Synthetic matching passes are not 50 volunteer clips/profile. Measure precision>=.95 and recall>=.85. |
| NFR-03 waiting | Fake-clock/block tests exist; representative pauses and blocks must show zero interruptions. |
| NFR-04 availability | Real warm-up gate now implemented but new GPU build unverified. Cloud uptime,5min monitoring and judge availability remain. |
| NFR-05 capacity | One conservative global GPU lease. Actual DR-6 capacity and N+1 busy wording must be measured. |
| NFR-06 privacy | No live recordings/transcripts persisted by app; hashed credentials, deletion and consent retention exist. Audit third-party NeMo logs (currently prints boosted words), Phoenix spans14d, weekly cards12weeks, external stores/backups and Hermes memory. |
| NFR-07 security | Device enrollment, signed15min production tokens, admission-time verification, Origin allowlist, role checks, shared leases and secret redaction exist. Production MFA/magic links/PIN, TLS/proxy/private ingress and pinned sandbox runtime remain. |
| NFR-08 accessibility | Frontend-owned design-system MUSTs and axe/browser testing remain; backend errors need frontend integration. |
| NFR-09 claims | Final README/screens/agent/video wording review required; do not claim SLT review without signed evidence. |
| NFR-10 cost | Budgeted app calls and AI switch exist. Cloud billing alerts, actual spend/uptime costs and shared agent budget remain. |

## Architecture decisions and gates

- D-01 controller: preserved; no model owns timing or success decisions.
- D-02 ASR: configured model and160ms framing present; exact checkpoint pin and
  due-word/name boosting audit remain.
- D-03 advisory Parakeet EOU: not implemented.
- D-04 Magpie: model loads; verify Aria speaker mapping rather than assume index0.
  WSOLA0.8, gaps500ms and normalization implemented; blind listening G-06 remains.
- D-05/06 Token Factory: both model IDs tested once, accepted JSON and one live
  pipeline reply. Client-per-loop overhead, Instructor/schema and20/20 evidence open.
- D-07/08 Pipecat1.12 + plain WS/AudioWorklet: implemented and user GPU-tested.
- D-09 hosting: CPU/GPU separation and containers implemented locally. Nebius
  Serverless L40S eu-north1, CPU API and finite CPU Job deployment not performed.
- D-10 storage: PG adapter/migrations0005 exist. Fresh managed TLS connection,
  schema migration/import and two-process restart need actual validation. Do not
  run destructive integration tests against the real application database.
- D-11 queue: current NightlyWorker is explicitly development-only, not saq0.26.4
  Postgres cron dispatch of finite Serverless Jobs. This implementation remains.
- D-12 carer: scoped APIs/plugin exist; Hermes/NemoClaw/OpenShell/Telegram do not yet
  have live runtime acceptance. G-05's plain-bot fallback requires documented failure.
- D-13/14 FSRS/pronunciation: required libraries and offline assets implemented;
  representative acceptance remains. No vector database or unapproved model swap.
- D-15 tracing: no Phoenix/OTel pipeline yet; log redaction alone is insufficient.
- D-16 Python3.12 and package layout present; full Linux uv lock/toolchain and
  strict static checks need completion. Main GPU dependencies are constrained,
  not a complete immutable release lock/digest.
- D-17 own validators preserved. No new guardrail framework introduced.
- D-18 judging: text/replay availability fromOct30; voice24/7 Dec1-Dec15 requires
  deployed monitoring/capacity/cost plan. Dates are workbook commitments.
- D-19 MIT/NOTICE exist; final dependency/image license review remains.
- D-20 AI practice partner wording remains; final claims review still required.
- M1-M5 modes: generic prompted practice is not complete explicit mode support;
  photo/object storage, M2/M3 phrase scope,5min short-day and fixed script are open.
- G-01 billing requires actual supported account evidence; credentials are pending.
- G-02 needs10min WebSockets and<200ms RTT fromPakistan AND UK; local echo is not it.
- G-03 requires20/20 valid nonempty raw JSON per model or documented workbook fallback.
- G-04 representative clips, G-05 live agent, G-06 listening preference and G-07
  signed SLT review are external evidence; code cannot manufacture them.

## Next backend implementation order while cloud access is pending

1. Durable saq/Postgres dispatch, per-person timezone/region and weekly storage/outbox;
   finite job runner/image and idempotent paid-call reservations.
2. Hermes/sandbox/Telegram runtime with scoped tools, budget/kill switch, real
   safety/weekly delivery and deletion integration.
3. Production identity/PIN, advisory EOU, verified voice, explicit modes and photo
   object lifecycle; coordinate frontend contracts rather than invent UI completion.
4. Phoenix instrumentation and retention, model-client latency/schema improvements,
   immutable Linux dependencies/images and representative acceptance fixtures.
5. Actual managed PG/TLS and cloud ingress, G-02, GPU warm-up/load/uptime/billing gates.

## Apply this audit's fixes on the GPU machine

Keep the stable image available. Copy the update files over the project without
replacing .env.split, DB/WAL, virtualenv or model caches. End sessions and keep AI off:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m patient_listener.tools.switch --db pl.db --ai-enabled false --reason backend-readiness-check
docker build -f deploy/Dockerfile.voice-backend-update -t patient-listener-voice:readiness .
```

Stop the API and old voice container gracefully. Restart the API from this updated
source with services run api. Start voice with:

```bash
PL_VOICE_IMAGE=patient-listener-voice:readiness bash scripts/run_local_voice_container.sh
```

Successful startup should log the synthetic inference warm-up pass. Voice /healthz
now returns200 voice_ready only after actual warm-up, with warmup_passed:true and
production_acceptance_verified:false. A Triton/compiler failure should now prevent
startup instead of reaching the first patient. No paid model calls occur in warm-up.
Test voice, Stop, hint rendering, Saving-energy rest/resume and cap behavior. Actual
frame-to-audio timing still needs tracing/measurement. Roll back to compiler-fix and
the corresponding host source together if acceptance fails.

## Verification at this checkpoint

All50 offline unittest modules passed in isolated processes:494 tests discovered,
480 passed and14 opt-in PostgreSQL tests skipped. All24 existing browser Node tests
passed. Twenty new tests cover deadlines, rest flow, warm-up and health semantics.
Whitespace checks passed. No GPU/model downloads, live calls, deployment or database
migration occurred during these tests. The first monolithic runner stalled in
framework test cleanup with a Starlette portal error; the bounded isolated rerun
completed without failed/timed-out modules. Treat this as a test-runner stability
issue to investigate, not deployed performance evidence.

The new startup ASR warm-up and rest/deadline changes have NOT yet been run on the
user's GPU. Earlier user acceptance applies to b48578c, not this uncommitted update.
No credentials are needed to continue the remaining code tasks listed above;
cloud account access is needed for actual hosted PG, deployment and billing gates.
