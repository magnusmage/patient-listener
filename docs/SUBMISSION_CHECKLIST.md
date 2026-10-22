# Submission readiness audit and three-day execution checklist

> **Historical snapshot:** for the current code/workbook review at `c928b1f`, see [Progress audit - 21 October 2026](PROGRESS_AUDIT_2026-10-21.md). Older gaps and next steps below may be superseded.

**Audit date:** 21 October 2026, Asia/Karachi.  
**Source:** `C:/Users/Mage/Downloads/Patient Listener Workbook v1.html`.  
**Target:** all workbook MUST requirements plus the submission deliverables; no silent scope cuts.  
**Access:** user confirmed all service access is available. Team member names and specific role assignments still need confirmation.

## How to read this audit

This is a code-and-document audit, not a production acceptance certificate. `Core tested` means local logic/tests exist; it does not mean the complete deployed requirement passed. `Partial` means a usable part exists but a required boundary or acceptance check remains. `Missing integration` includes scaffolds and UI controls without a real backend operation. `Unverified` means acceptance evidence is absent.

The last backend run reported **193 passing tests and green local release gates**. These were mainly synthetic/fake model and controller checks. In particular, the fallback gate name does not by itself establish real wall-clock audio latency. No new test run was needed for this documentation-only audit. No live Nebius response, deployed GPU voice session, PostgreSQL service, or delivered Telegram message has been verified in this chat.

The workbook contains its own deadline and judging-window claims. They are recorded as workbook claims, not independently verified current contest rules. Treat the user's three-day deadline as the execution constraint. Day 1/2/3 below means 21/22/23 October if work begins today; confirm the actual cutoff hour with the team.

## Critical findings that change the earlier progress summary

- The real voice pipeline is unfinished: `build_pipeline` still raises `NotImplementedError` when its runtime check succeeds. The `nemo_toolkit` import check itself needs replacing with the real installed NeMo interface; installed package presence is not model readiness.
- Audio events use a new private `feed` protocol, while `ports.Asr` still defines `stream`; reconcile this before constructing the real adapter. TTS typing promises an iterable while the pipeline consumes an async iterable; reconcile and test the actual SDK contract.
- `AudioPipeline.say` is not connected to outgoing session actions. Browser binary output playback and enforced half-duplex coordination are missing.
- The live loudness flow is simulated, not PCM measurement; elapsed session caps have configuration but no enforcement timer.
- Console Add, settings, consent toggles and deletion can change browser-only data. Their appearance is not evidence of persisted server changes. CSV export currently omits real backend attempts.
- PostgreSQL, migrations, Phoenix instrumentation, saq scheduling and the Hermes/NemoClaw carer integration are not implemented in the inspected source tree.
- FSRS is a simplified local stand-in; matching and pronunciation helpers also include stand-ins. Dependencies being listed does not establish their use.
- Default app startup seeds demo records into the selected store repeatedly. Separate judge seeding from persistent application startup and prove restart does not overwrite changes or resurrect deleted data.
- Token Factory is wired and mocked-tested, but currently uses `json_object`, not strict schema output. The workbook permits that fallback only after G-03 evidence. Current reply retry receives another full timeout and no rejection reason; verify/fix the total budget and correction prompt.
- Database AI state initializes true, not from `AI_ENABLED`. Model selection at session construction can also prevent re-enabling a template-only session without reconnecting. Nightly model paths do not yet demonstrate the per-call kill-switch policy.
- Local token checks are useful but do not provide production MFA, patient enrollment authorization, shared live-session locking or verified TLS deployment.

## Owners and immediate access checks

Suggested roles are **B** backend/AI (your role), **F** frontend, **I** infrastructure, **S** submission/review. These are proposed responsibilities, not assigned people. Confirm named owners before starting simultaneous work.

| Check | Owner | Evidence needed |
| --- | --- | --- |
| Token Factory access | B | Model-list response with Lightning/Super IDs; one schema-valid generated line with latency; never paste keys |
| Voice GPU access | B + I | Real NeMo/Magpie model load, microphone PCM recognized, sample output playable |
| Deployment | I | HTTPS API URL, WSS connection, secrets configured, restart procedure |
| Managed PostgreSQL | B + I | Successful connection and migration, scoped write/read after API restart |
| Agent/channel | B + I | Hermes/NemoClaw/OpenShell startup and a test Telegram delivery linked to the correct person |
| Auth provider | B + F + I | Selected passkey or magic-link MFA flow and redirect origins; judge exemption isolated |
| Work assignment | Team | Named owner for each row in the execution plan |

## Requirement-by-requirement acceptance checklist

Each row remains open until its full acceptance requirement has evidence, even where the local core is tested.

| ID | Workbook requirement | Audit status | Current evidence | Remaining acceptance work |
| --- | --- | --- | --- | --- |
| FR-01 | The microphone opens only after the person taps Start | Partial | web/client.js LiveDriver.start | Mic opens on Start; verify permissions, teardown and browser gesture in the real deployed flow. |
| FR-02 | The listener never produces audio while VAD reports speech | Partial | voice/controller.py; tests/test_controller.py | Core speech exclusion tested; real VAD and output overlap measurements missing. |
| FR-03 | Waits follow the merged profile: Finding words "mm" at 4.0 s, hint offer at 7.0 s, move on at 20.0 s of silence (±0.1 s) | Partial | voice/controller.py; tests/test_controller.py | Fake-clock timing exists; verify continuous VAD silence and deployed timing. |
| FR-04 | The mic is ignored while the app is speaking (half-duplex); "stop" and the Stop button still work | Missing integration | web/client.js LiveDriver.mute | Mute helper exists, but playback and automatic half-duplex coordination are missing; verify spoken Stop handling. |
| FR-05 | Stop ends audio within 200 ms and the session within 1 s | Unverified | app/session.py; web/client.js | Text stop exists; measure actual audio cancellation within 200 ms and session termination within 1 s. |
| FR-06 | Every spoken line is shown as a caption; the person can type an answer at any time | Partial | web/app.js; app/session.py | Typed input exists; every real spoken line and transient ASR caption must reach the rendered UI. |
| FR-07 | A session ends at the profile's cap (20 min Finding words; 10 min Saving energy) with "Well done today", unless the person switched the cap off | Missing integration | schemas.PauseConfig.max_session_min | Configured cap is not enforced by an elapsed-session timer; add cap expiry, no-limit behavior and closing wording. |
| FR-10 | Setup (P0) asks "What's hard for you when you talk?" with five cards; any number can be chosen; no diagnosis is asked or stored | Partial | schemas.py; web/app.js; app/deps.py | Needs schema and UI exist, but server sessions use seeded stored needs; persist setup and prove multi-profile selection reaches engine. |
| FR-11 | Profiles merge by: any "never" wins, longest wait wins, smallest limit wins | Core tested | voice/merge.py; tests/test_merge.py | Merge rules tested; still verify saved settings and patient overrides use them. |
| FR-12 | Getting words out: no "mm", no hint, no Help button, no banned phrase (DS-C05); the turn ends after ≥ 8 s silence only if Lightning says the text is complete, or on Done | Partial | voice/controller.py; voice/session.py | Silent-block and completeness logic tested; real model/VAD path unverified, current completeness transcript must cover required current-turn context. |
| FR-13 | Being heard: baseline = median dBFS of 5 phrases read at session start; "A bit stronger?" when an utterance is ≥ 2 dB below; no number shown or spoken | Missing integration | voice/loudness.py; app/session.py._heard | Pure baseline logic tested, but live app alternates simulated loudness. Implement real PCM measurement and five-phrase calibration. |
| FR-14 | Being clear: "What I heard" after every turn; an attempt is logged as found only after ✓ | Partial | voice/controller.py; app/bridge.py | Confirmation-before-found tested; verify What I heard after every relevant turn, including nonmatches. |
| FR-15 | Saving energy: max 15 turns, "Rest?" every 5 turns, no "one more" | Core tested | voice/controller.py; tests/test_controller.py | Turn cap/rest cadence tested; verify live UI resume does not skip or reset the wrong turn. |
| FR-20 | Hints are given only when the person says yes to "Want a hint?" or taps Help, one level at a time, in hint_order | Core tested | voice/controller.py; tests/test_hints.py | Consent-based level progression tested; real cached clip playback still missing. |
| FR-21 | No line says a not-yet-found practice word before hint level 3 | Partial | llm/validate.py; tests/test_validator.py | Reply validator tested; review all prompts, captions, cached clips and audio for early target disclosure. |
| FR-22 | Matching uses the score and thresholds in Definitions ; 0.60–0.89 asks "Did you say Leo?" | Partial | voice/matcher.py; text/fuzzy.py; text/phonetics.py | Local stand-ins tested; workbook RapidFuzz/Jellyfish implementation and real audio fixtures still require verification. |
| FR-23 | One attempt row per target per turn; no text or audio stored | Core tested | store/sqlite_store.py; tests/test_store.py | Attempt records omit audio/transcript; repeat checks for PostgreSQL and complete retention/log surfaces. |
| FR-24 | Lightning replies: one line, ≤ 15 words, validated; if late (1.5 s) or rejected twice, a template line plays | Partial | llm/token_factory.py; llm/reply.py; tests/test_token_factory.py | Mocked live integration tested. Verify real model, schema support and total 1.5 s budget across validation retry; current retries get a fresh budget and do not send rejection reason. |
| FR-40 | New words start as drafts; only a therapist, or the carer if no therapist is linked, approves them in the console | Partial | console_api.py approve; sqlite_store.py.console_approve_word | Role-scoped approval tested. Missing authenticated create-draft endpoint and UI wiring; Add currently inserts browser-only approved data. |
| FR-41 | An approved word gets a validated meaning line (Super), template sound and word lines, and audio clips for all three by the next nightly run | Partial | nightly.py; llm/plan.py; voice/clips.py | Template hint builder exists. Real Super + Instructor validation/retries, real cached clips and scheduled execution remain. |
| FR-50 | The carer agent turns a chat message into a draft and replies with a console link within 10 s | Missing | No carer agent adapter found in src | Implement authenticated patient-linked chat-to-draft tools and console link response; measure under 10 s. |
| FR-51 | "How's [name] doing?" is answered only with the weekly counts template; no interpretation | Partial | llm/templates.py | Fixed templates exist; connect agent to scoped weekly-count queries and prove it never interprets health. |
| FR-52 | The weekly card (Friday 18:00 local) lists words found without a hint, new words, and the fixed safety line | Partial | nightly.py; llm/plan.py.weekly_card | Card template exists. Correct new-word window, per-person time zone, Friday 18:00 delivery and persistence remain. |
| FR-60 | Console grid shows per word per day: ✓ / M / S / W / –, with no suggestions or predictions | Partial | app/console_api.py.grid; tests/test_app_console.py | Scoped grid API exists; verify hint-order swaps map M/S correctly and use patient-local dates. |
| FR-61 | Therapist (or carer, only when no therapist is linked) can change needs, waits (within the PauseConfig ranges), hint order and session cap. The person can always lengthen or switch off any wait or the session cap in P7 without a PIN; the PIN guards only needs, hint order, shortening limits and consent | Missing integration | app/console_api.py.settings GET; web/console.html T5 | No settings write API. Persist needs/waits/hint order/caps; enforce role and PIN policy, patient lengthening/no-limit rights and live application. |
| FR-62 | Export (CSV) and delete-everything; deletion completes within 24 h and is confirmed | Missing integration | store export/delete helpers; web/console.html | No authenticated export/delete API; UI currently exports local rows and clears only browser data. Implement actual complete deletion and confirmation. |
| FR-63 | The word list accepts "my phrases" (kind = phrase, ≤ 60 characters), approved like words, practised in M2/M3, and exported as plain text in T6. No audio is recorded or stored | Partial | schemas.WordEntry; tests/test_schemas.py | Phrase type and limits exist; end-to-end draft/approval/practice/export and M2/M3 mode behavior remain. |
| FR-80 | Stroke-sign phrases stop the session and show the safety card with the local number (999 UK, 911 US, 1122 Pakistan); the linked carer gets a message within 10 s | Partial | voice/safety.py; tests/test_safety_stop_session.py | Safety stop tested. No delivered carer notification; app region defaults UK, so propagate actual region and test localized numbers. |
| FR-81 | Distress phrases (including short non-fluent ones) show the support card; carer told only if consented | Partial | voice/session.py; store consent helpers | Core consent condition tested; notification flag is not delivery. Persist consent changes and prove no delivery when consent absent. |
| FR-82 | Profile red flags (hoarse 3+ weeks, new adult stammer, choking, breathless, sudden hearing loss) show the right card; loudness practice pauses for hoarseness | Partial | voice/safety.py; tests/test_safety.py | Rules tested; verify live transcription, cards, audio cancellation and loudness pause. |
| FR-83 | Practice data is never used to infer a health change | Core reviewed | schemas.py; llm/templates.py | No diagnosis field; review actual agent/model outputs and all exposed statistics for health-change inference. |
| FR-84 | AI_ENABLED=false switches every model line to templates without a redeploy | Partial | llm/factory.py; voice/session.py; tools/switch.py | Reply/completeness checks use database flag, but fresh DB defaults true rather than env; ensure all nightly/model paths check it and off-to-on works without redeploy. |
| FR-90 | Judge mode: three seeded demo people (Margaret: Finding words; Daniyal: Getting words out; Joseph: Being heard), a demo therapist login without MFA, a "simulate carer message" box, replay mode, and the live trace screen (J1) showing model IDs and latency | Partial | app/deps.py; console_api.py.demo_session; web/app.js | Seeded people and isolated judge access exist; missing working simulated carer flow, scripted audio replay and real model-ID/latency trace. |
| NFR-01 | Hint audio starts ≤ 300 ms (p95) after "yes" or Help; live reply first audio ≤ 1.0 s p50, ≤ 1.5 s p95 after the controller decides to speak | Unverified | No deployed audio measurements | Record hint and reply first-audio percentiles from real audio path; simulated release gates are not latency measurements. |
| NFR-02 | Found-word precision ≥ 0.95; recall ≥ 0.85 on the W set | Unverified | tests/test_release_gate.py | Synthetic matcher precision gate exists; real W-set ASR precision and recall evidence missing. |
| NFR-03 | 0 interruptions for pauses ≤ 15 s; 0 sounds during blocks in Getting words out | Partial | tests/test_controller.py; tests/test_release_gate.py | Simulated waiting gates pass; prove zero audible overlaps with VAD and fixture recordings. |
| NFR-04 | Judge walkthrough works from Oct 30 to Dec 15 12:00 PST; live voice 24/7 Dec 1–15; /healthz only green after a warm-up pass | Missing integration | No warm health endpoint found | Deploy /healthz that passes only after model/cache warmup; provision workbook judging uptime and monitoring. |
| NFR-05 | Sessions per GPU measured in DR-6; session N+1 gets "The listener is busy, please try in a few minutes" | Missing | No measured GPU concurrency limit | Measure capacity and enforce busy rejection with correct cleanup and user-visible response. |
| NFR-06 | No audio, transcripts or diagnosis stored; logs and traces hold IDs and timings only; traces kept 14 days; weekly cards 12 weeks; consent records for the account's life + 2 years | Partial | attempt schema; access_log.py | Access-log credential redaction tested. Audit UI traces, reverse-proxy logs, audit detail text, model instrumentation, retention and deletion; no Phoenix retention jobs yet. |
| NFR-07 | TLS everywhere; session tokens valid 15 minutes, checked when the WebSocket connects (an open session continues), bound to one device; one live session per person; secrets only in env vars; OpenShell ≥ 0.0.34; PIPECAT_WEBSOCKET_AUTH=token ; no speaker embeddings | Partial | tokens.py; session_registry.py; config.py | Device-bound tokens/TLS guards exist. Shared locking, real TLS, console credential transport, session issuance authorization outside judge personas, trusted proxies and OpenShell deployment need verification. |
| NFR-08 | Every MUST rule in the Design system | Unverified | web/ and browser tests | Run full workbook A-set plus axe, keyboard, zoom and contrast checks on deployed patient and console flows. |
| NFR-09 | All screens, README, description and video pass the claims table | Unverified | README.md; web/; NOTICE | Review all screens, README, submission and video against claims table; no blanket clinical endorsement. |
| NFR-10 | Development ≤ $50 of GPU; judging ≤ $570 (live voice ≈ $525 + CPU ≤ $40); Token Factory within credits | Unverified | No cloud billing evidence in repository | Configure budget alerts and record real GPU/session cost and judging-duration cost. |

## Architecture decisions that must be delivered or explicitly gated

| Decision | Required completion | Evidence / approved fallback |
| --- | --- | --- |
| D-01, D-17 | Pure controller decides turns; code validator gates generated lines | Existing core retained; audit every new output path |
| D-02, D-03, D-07 | Nemotron streaming ASR, Silero VAD, Parakeet EOU input, Pipecat 1.12 | Real long-pause fixtures; EOU never independently ends a turn |
| D-04 | Magpie Aria, 22.05 kHz, sentence streaming; WSOLA 0.8x hints plus 500 ms gaps | Real cached clips, normalization and listening review; G-06 fallback only if measured |
| D-05, D-06 | Lightning live and Super nightly, thinking off, schema validation, Instructor nightly | Real API evidence; G-03 determines any schema fallback |
| D-08 | Plain WebSocket/AudioWorklet browser | 16 kHz input, binary playback output and control-message coexistence |
| D-09, D-10 | Nebius CPU/GPU endpoints, Serverless Job, Managed PostgreSQL | Public HTTPS/WSS and persistent deployed data; G-02 VM fallback only if endpoint test fails |
| D-11 | saq on PostgreSQL, patient-local scheduling | Do not substitute Redis/arq; prove 02:00 work and Friday 18:00 delivery |
| D-12 | Hermes v0.19 in NemoClaw, pinned OpenShell v0.0.116, Telegram | Existing config only requires a lower minimum; pin deployment. G-05 plain-bot fallback requires recorded failed gate |
| D-13, D-14 | Real FSRS library and pronunciation via CMUdict/epitran | Tests compare adapter behavior, personal names and due-word plans |
| D-15 | OpenTelemetry to self-hosted Phoenix without text | Real spans, IDs/timings only, retention configured |
| D-16 | Python 3.12, uv, ruff/mypy/pytest | Reproducible platform-appropriate lock, lint/type/test commands and CI |
| D-18 | Accessible judge mode and workbook availability window | Deployment/monitor evidence, independently check current submission dates |
| D-19, D-20 | MIT, third-party NOTICE, practice-partner positioning | Licence and wording review of all submission surfaces |

Dependency compatibility deviation already documented in `DEPENDENCIES.md`: the installed LLM client is OpenAI 3.3.0 with Instructor 1.17.0 and Tenacity 9.2.1. The Windows/Python 3.12 hash lock is not a Linux deployment lock. Preserve and explain this correction; do not silently claim exact workbook version compliance.

## Gate and dry-run evidence

All gates are pending external evidence unless stated otherwise. Do not take an allowed fallback merely to save implementation time.

| Gate | Evidence to collect | Workbook fallback if gate fails |
| --- | --- | --- |
| G-01 | Working lawful Nebius billing/account setup; user says access is available, archive proof privately | Supported-country teammate account/team arrangement per workbook; no false residence |
| G-02 / DR-7 | Ten-minute endpoint WebSocket echo from Pakistan and UK, all frames returned, RTT under 200 ms | Voice on Nebius L40S Compute VM; API/job stay Serverless |
| G-03 / DR-0, DR-5 | Real model IDs; 20/20 nonempty valid JSON calls for both models with thinking off; validate reveal rejection | json_object + prompt schema + strip think + template on failure |
| G-04 / DR-1, DR-4 | 50 consented volunteer clips per demo profile with boosting; precision >=0.95, W-set recall >=0.85; nine-second silence retained | Raise logging threshold to 0.95 and confirm below, with tests |
| G-05 | Hermes/NemoClaw scenario 8 succeeds five consecutive times | Plain Telegram bot with same tools; document attempt in feedback |
| G-06 / DR-2 | Three listeners compare 0.8x clips against normal; cached first audio under 300 ms | Normal clips with 500 ms gaps |
| G-07 | Signed SLT review note if claimed | Omit SLT-review claim when absent; do not fabricate evidence |
| DR-3 | Workbook timing acceptance suite | Local fake-clock tests exist; map all required cases |
| DR-6 | Browser-to-real-model voice loop, measured sessions per GPU, latency under load | Record capacity limit; enforce busy response |
| DR-8 | Recorded VoiceChat baseline if workbook deliverable retained, licensing checked | Baseline is video-only, not the product voice backend |

## Three-day execution order

This is a dependency order with proposed concurrent ownership, not a completion guarantee. All required work remains in scope. The full remaining workload is high risk for one developer in three days; name owners and compare actual results to each checkpoint.

### Day 1: real service proof and persistent foundations

1. **B + I:** run real Token Factory model-list/schema checks and GPU model-load spike first. Save sanitized IDs, timings and failures.
2. **I:** deploy HTTPS API and WSS echo; run G-02 and provision Managed PostgreSQL plus Phoenix and secret injection.
3. **B:** implement PostgreSQL repository/migrations; isolate judge seeds, ensure startup and deletion are safe, add shared session claim/release.
4. **B + F:** finish ASR/VAD/EOU contract and browser playback protocol, then prove first microphone-to-text-to-spoken-response round trip.
5. **F + B:** begin persistent console draft/settings/consent/export/delete flows and auth provider integration using agreed API contracts.

**Checkpoint:** real API calls and GPU speech components must work today. A seeded person and attempt survive API restart in PostgreSQL; a WSS browser connection stays up. If these fail, immediately execute only the workbook's applicable gated fallback and record the result.

### Day 2: required user flows

1. **B + F:** complete voice turns, cached hints, half-duplex, Stop cancellation, partial/final caption handling and model failure behavior.
2. **B:** real five-phrase loudness baseline, session duration caps, selected profile persistence, phrase modes, actual FSRS/pronunciation adapters.
3. **B:** Super + Instructor nightly hint generation, validated retries, real clip rendering, plan build and Friday card content.
4. **B + I:** saq/PostgreSQL scheduling with person-local time zones; Hermes/NemoClaw chat-to-draft, count reply and timed notification delivery; idempotency/retries without duplicate alerts.
5. **B + F:** finish role-checked persistent console APIs, production auth flow, person override/PIN rules, consent changes and complete export/delete behavior.

**Checkpoint:** use a fresh browser and demonstrate carer message -> saved draft -> therapist approval -> nightly hints -> patient practice -> persisted attempt -> progress/counts -> consent-correct notification. Show export and deletion alter the real data. Exercise jobs using controlled timestamps instead of waiting overnight.

### Day 3: acceptance, fixes and submission

1. **B + F + I:** run the full FR/NFR acceptance matrix, real voice fixtures, failures, GPU load and endpoint disconnect tests. Fix blockers before recording.
2. **I:** verify warm health checks, judging access, monitoring, cost alerts, backups/restore, secrets and required retention/deletion jobs.
3. **F + S:** complete keyboard/zoom/axe and claims review; record a clean judge walkthrough with real model IDs and latency.
4. **S + B:** publish a reproducible public repo with licences, assets, seeds, clip-build script, setup/deployment instructions and exact known limitations.
5. **S:** produce the required video, feedback and submission form. Reserve the final half-day for a fresh-machine walkthrough, external URLs and upload checks.

**Checkpoint:** every required row has a passing acceptance artifact or an explicitly permitted, evidenced workbook fallback. An honest blocked row remains blocked; a unit test does not close a deployment requirement.

## Submission deliverables beyond application code

The workbook describes these deliverables; verify the actual event form/rules separately before final submission.

- [ ] Public working project URL with unrestricted isolated judge access, text/replay, simulated carer input and J1 real model/latency trace.
- [ ] Public source repository with MIT licence, accurate third-party NOTICE, all needed assets and build/run/deploy instructions. Existing local commits do not prove a public repository exists.
- [ ] Real Nvidia and Token Factory use shown with sanitized model/latency evidence.
- [ ] Public YouTube demonstration shorter than three minutes; workbook target 2:45. Verify permitted media/branding and consent for all people/recordings.
- [ ] Required Token Factory / AI Cloud / Nvidia feedback in the submission form; create `docs/FEEDBACK.md` as supporting build log, not a substitute for the form.
- [ ] Intended-use/system-card documentation and wording review; no unsupported therapy, assessment or recovery claims.
- [ ] Fresh-profile judge walkthrough under five minutes and documented availability/uptime plan for the judging window.
- [ ] Participant/team details, external URLs, permissions and submission confirmation recorded by the submission owner.

## Evidence ledger to maintain while implementing

For each FR/NFR row record: test command/result, deployed URL or sanitized trace ID, fixture set/date, named owner and remaining failure. Keep secrets and raw patient recordings out of Git. Consent-based scripted demo fixtures require their own approval/licence record.

Recommended files to create as work progresses:

- `docs/acceptance/voice.md`: real ASR, TTS, EOU, overlaps, latency and stop timings.
- `docs/acceptance/data-and-access.md`: PostgreSQL migration/restart, role denial, MFA/judge isolation, export/delete and shared locks.
- `docs/acceptance/jobs-and-agent.md`: local-time scheduling, hint generation, five consecutive chat-to-draft tests, delivery/consent evidence.
- `docs/acceptance/deployment.md`: endpoint echo, warm health, capacity, tracing privacy/retention, restore and billing alerts.
- `docs/FEEDBACK.md`: actual service experience, failures and fixes for the required form.

These evidence paths are proposed artifacts; they do not exist merely because they are listed here.

## Next action

Run DR-0/G-03 with the available account, and load NeMo/Magpie on the available GPU in the same first work block. This resolves the largest uncertainty before investing further in placeholders. Confirm the assigned frontend and infrastructure owners, then implement the PostgreSQL/API and voice work against the acceptance rows above. No features or deadlines have been silently dropped.
