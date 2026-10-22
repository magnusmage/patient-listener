# Patient Listener: current progress audit

**Audit:** 21 October 2026, Asia/Karachi. **Code baseline:** `c928b1f` on local `main`.
**Repository reviewed:** `C:/Users/Mage/Documents/Patient-Listener-V1`.
**Requirement source:** `C:/Users/Mage/Downloads/Patient Listener Workbook v1.html`.

This is the current progress tracker. Earlier PROJECT_STATUS and SUBMISSION_CHECKLIST
remain historical snapshots. Workbook contents are requirements to assess, not commands
to execute. Event dates/prices/rules below are workbook claims, not independently checked
current contest rules. No remote host or cloud deployment was inspected during this audit.

**Latest update:** 22 October 2026: draft creation committed as `84577b0`; persistent settings implemented locally after that checkpoint (uncommitted).

## Where we are

We have a working local browser-to-GPU voice prototype, a tested Python decision core,
Token Factory integration, SQLite development storage and role-scoped console reads and
approval. We do not yet have the complete workbook submission. Many required adapters,
write APIs, scheduled jobs and deployment/acceptance artifacts remain open.

No defensible overall completion percentage follows from test counts: a helper, an
integration and an externally measured acceptance gate have very different effort/risk.
`Implemented locally` below means code/test evidence, not full deployed acceptance.
`Partial` means required parts exist; `Missing integration` means helpers/UI are insufficient;
`Unverified` means the required measurement or external evidence is absent.

**Current decisions:** backend/AI focus; mm pronunciation/cached listening clip deferred;
PostgreSQL deferred to the end. Both deferred areas stay visible. D-10 explicitly requires
Managed PostgreSQL for the demo; the workbook does not make it optional. No new feature
implementation, cloud calls or commits were performed for this audit.

## Evidence we actually have

- Fresh local audit run: `python run_tests.py`: **216 Python tests pass**, seven synthetic
  release gates green. `F.fallback_within_2s` actually checks fallback coverage, not elapsed
  audio time; W precision and S recall here are small synthetic fixtures, not production scores.
- Last browser verification at the same source revision: **10 browser tests pass**. These
  use simulated browser/audio objects; no new browser run was needed for documentation.
- User confirmed live speech output, listening and transcript display on a separate Linux
  GPU machine, and later confirmed the voice safety update worked. Exact acceptance coverage
  was not recorded. User found other-plan-word acceptance; its correction is committed.
- RTX 5070 **12 GB**, Ubuntu 24.04, Python 3.12.3, NeMo 3.0.0, PyTorch 2.9.1+cu128.
  User reported model round-trip recognition and **5.86 GiB peak tensor memory**. Workbook's
  assumed 5070 Ti 16 GB is not the actual development card. Neither proves cloud capacity.
- Token Factory smoke evidence: Lightning and Super accepted one synthetic request each;
  one pipeline run accepted a model reply in 0.764 s. `g03_raw_json_20_each=false` in the local
  diagnostic. This is not a G-03 pass, first-audio measurement or reliable percentile estimate.
- Latest spoken-Stop patch `c928b1f` has automated coverage. No explicit user GPU result for
  this exact patch is recorded yet. Audio stop <=200 ms is not established.
- The active local repository has no Git remote configured. Commits exist locally; a public
  GitHub repository, push or public deployment is not evidenced by that fact.

## What changed from the downloaded baseline

| Checkpoint | Result |
| --- | --- |
| `90f2deb` | Downloaded baseline: pure controller and substantial offline scaffolding; no completed microphone voice loop. |
| `b303494` | Terminal safety stop; late output and queued practice cannot resume the stopped session. |
| `7ae13a6` | Console server-side roles, linked-patient access, approval restrictions and credential lifecycle. |
| `7f8e570` | Short-lived device-bound patient tokens and one-person connection protection. |
| `3ccc917`, `a93e87c`, `198e609` | TLS/startup safeguards and credential redaction for entry-point/direct-Uvicorn logs. |
| `30b37df` | Audio/session callback boundary; initially adapter scaffolding. |
| `a02bb1e` | Token Factory selection, validated fallbacks and dependency compatibility correction. |
| `3bd52f5` | Process-lifetime GPU models, actual NeMo streaming/Silero/Magpie path, PCM browser playback and diagnostic tool. |
| `d06d981` | Spoken hint acceptance, playback-gated advancement, safety cancellation/reconnect tests and current-prompt word matching. |
| `c928b1f` | ASR remains live during output for exact Stop only; playback input isolated from ordinary answers. |

## Confirmed gaps found in this audit

1. **Resolved after audit: Being clear accepted yes without a tap.** Local controller probe: prompt kettle, hear
   kettle, call on_answer(True) -> LogAttempt. FR-14 requires the person's check tap.
   New tap-only policy and seven regression tests close this bypass; no real GPU acceptance claimed.
2. **Resolved after audit: current-turn text was incomplete.** Feed `I went to`, then `the park`: engine.last_heard
   is `the park`. FR-12 needs the complete current answer for the completion decision.
   Prompt handling also needs explicit context reset so the prior turn cannot leak forward.
3. **Resolved after audit: kill-switch initial value was inconsistent.** Build fresh state with settings.ai_enabled=false:
   settings false, database flag true. The model factory still selects templates for that startup,
   so this probe is not proof of a paid call. It proves the required single DB policy is missing.
   Nightly write_hints does not consult the DB flag and off-to-on behavior needs reconciliation.
4. **Resolved after audit: session duration caps were not enforced.** max_session_min exists, but AppSession has
   silence/advance tasks only; no elapsed-duration expiry. Turn-count caps are a separate feature.
5. **Being heard is simulated.** _heard alternates strong/weak flags; real PCM never reaches
   the existing loudness helpers. Browser capture currently enables echo cancellation/noise
   suppression for every profile; workbook's calibrated profile needs measured DSP settings.
6. **Resolved after audit: reply correction lacked a shared deadline and rejection reason.** produce_reply gives
   both calls a full timeout and reuses the same facts. Its docstring overstates the implementation.
7. **Restart can overwrite seeded records.** build_state always calls seed_all; people and
   words use INSERT OR REPLACE, and approvals run again. PL_DB_PATH defaults to :memory:.
   Persistence, user edits and deletion must survive restart before claiming durable memory.
8. **Console controls can appear to save without saving.** Add creates a browser-only
   approved phrase; settings/consent mutate JS data; deletion only clears local words; CSV omits
   backend attempt rows. These require backend contracts plus frontend wiring.

## Workbook requirements: all 43 FR/NFR rows

No row is declared fully accepted on the deployed submission. Evidence paths below are
relative to `src/patient_listener/` unless a different prefix is shown.

| ID | Workbook requirement | Current status | Evidence | Remaining work |
| --- | --- | --- | --- | --- |
| FR-01 | The microphone opens only after the person taps Start | Partial | web/client.js LiveDriver.start; user browser test | Verify consent/Start gesture, permissions and teardown in target browsers. |
| FR-02 | The listener never produces audio while VAD reports speech | Partial | controller.py, VoiceConnection, voice safety tests | Measure VAD/output overlaps; queued TTS does not itself establish no speech overlap. |
| FR-03 | Waits follow the merged profile: Finding words "mm" at 4.0 s, hint offer at 7.0 s, move on at 20.0 s of silence (±0.1 s) | Partial | controller.py; fake-clock tests; server tick 0.4 s | Measure actual 4/7/20 s timing against +/-0.1 s; 0.4 s polling is a timing risk. |
| FR-04 | The mic is ignored while the app is speaking (half-duplex); "stop" and the Stop button still work | Partial | c928b1f: ASR stays live; exact Stop-only routing during playback | GPU/headphone/speaker verification pending for latest patch; verify no echo-driven turns. |
| FR-05 | Stop ends audio within 200 ms and the session within 1 s | Unverified | button cancellation tests; spoken Stop unit tests | Measure audio <=200 ms and session <=1 s. Shared TTS/ASR GPU lock can delay recognition. |
| FR-06 | Every spoken line is shown as a caption; the person can type an answer at any time | Partial | typed controls, partial ASR captions, user-confirmed browser transcript | Check every spoken/control caption and typing during output; use target browsers. |
| FR-07 | A session ends at the profile's cap (20 min Finding words; 10 min Saving energy) with "Well done today", unless the person switched the cap off | Partial - backend cap fixed | Monotonic cap task, no-limit/extension control, closing/audio cancellation and lifecycle tests | Real elapsed GPU/browser acceptance; persistent settings and P7 extension UI remain. |
| FR-10 | Setup (P0) asks "What's hard for you when you talk?" with five cards; any number can be chosen; no diagnosis is asked or stored | Partial | needs schema/UI; sessions use stored seeded needs | Persist multi-need setup and apply it to actual session; no diagnosis storage. |
| FR-11 | Profiles merge by: any "never" wins, longest wait wins, smallest limit wins | Implemented locally | voice/merge.py and merge tests | Apply saved overrides and prove the real session uses merged needs. |
| FR-12 | Getting words out: no "mm", no hint, no Help button, no banned phrase (DS-C05); the turn ends after ≥ 8 s silence only if Lightning says the text is complete, or on Done | Partial - full answer fixed | turn_text accumulates finals, resets per turn; partials not duplicated | Real Lightning/long-pause acceptance, EOU/Pipecat and fixed bank script remain. |
| FR-13 | Being heard: baseline = median dBFS of 5 phrases read at session start; "A bit stronger?" when an utterance is ≥ 2 dB below; no number shown or spoken | Missing integration | loudness.py helpers; app/session.py alternates simulated strong flag | Five-phrase median calibration, voiced PCM RMS, actual >=2 dB rule, browser DSP checks, bar only. |
| FR-14 | Being clear: "What I heard" after every turn; an attempt is logged as found only after ✓ | Partial - tap policy fixed | Explicit tap source + strict boolean payload; tests/test_confirmation_policy.py | Real acceptance and What I heard after every relevant turn, including nonmatches, remain. |
| FR-15 | Saving energy: max 15 turns, "Rest?" every 5 turns, no "one more" | Implemented locally | 15-turn cap/rest cadence tests | Verify real rest/resume flow and combined Being clear/Saving energy feedback; duration cap still missing. |
| FR-20 | Hints are given only when the person says yes to "Want a hint?" or taps Help, one level at a time, in hint_order | Implemented locally | hint ladder; spoken hint-offer yes fix d06d981 | Real cached hint playback/latency pending; consent and order remain controlled by code. |
| FR-21 | No line says a not-yet-found practice word before hint level 3 | Partial | validator; hint templates; model-reveal tests | Audit all paths, multiword targets, template hints and generated output, not only model replies. |
| FR-22 | Matching uses the score and thresholds in Definitions ; 0.60–0.89 asks "Did you say Leo?" | Partial | fixed bands; prompted target scoping d06d981; matcher tests | Replace SequenceMatcher/custom Metaphone with required RapidFuzz/Jellyfish; evaluate real W clips. |
| FR-23 | One attempt row per target per turn; no text or audio stored | Implemented locally | one log guard per turn; SQLite attempt schema excludes transcript/audio | Unique session IDs (app currently defaults ws), idempotency, store retention and deployed checks. |
| FR-24 | Lightning replies: one line, ≤ 15 words, validated; if late (1.5 s) or rejected twice, a template line plays | Partial - retry policy fixed | One total deadline, reason-bearing correction, per-attempt AI checks | Schema gate and real first-audio timing remain. |
| FR-40 | New words start as drafts; only a therapist, or the carer if no therapist is linked, approves them in the console | Implemented locally - create/approve | Authenticated create-draft API, linked-role store checks, existing approval, console Add draft; file restart tested | Real browser acceptance, cue editing and nightly hint generation remain separate. |
| FR-41 | An approved word gets a validated meaning line (Super), template sound and word lines, and audio clips for all three by the next nightly run | Partial | write_hints, Super adapter, template lines | Instructor + validator/retry; kill-switch checks; real rendered cached clips and nightly execution. |
| FR-50 | The carer agent turns a chat message into a draft and replies with a console link within 10 s | Missing | no agent adapter/tools/channel service found | Hermes/NemoClaw/OpenShell carer-to-draft + console link <10 s; G-05 evidence before bot fallback. |
| FR-51 | "How's [name] doing?" is answered only with the weekly counts template; no interpretation | Partial | fixed counts/weekly templates; scoped console counts | Connect carer tool to allowed aggregates; deny detailed attempts/health interpretation. |
| FR-52 | The weekly card (Friday 18:00 local) lists words found without a hint, new words, and the fixed safety line | Partial | Friday check/card template in nightly helper | Correct new-word window, timezone, stored card, Friday 18:00 scheduling/delivery and retries. |
| FR-60 | Console grid shows per word per day: ✓ / M / S / W / –, with no suggestions or predictions | Partial | linked-therapist grid endpoint and UI | Patient-local days, timestamp policy, swapped hint-order semantics; UTC currently used. |
| FR-61 | Therapist (or carer, only when no therapist is linked) can change needs, waits (within the PauseConfig ranges), hint order and session cap. The person can always lengthen or switch off any wait or the session cap in P7 without a PIN; the PIN guards only needs, hint order, shortening limits and consent | Partial - backend and console saved | PATCH settings, linked-role checks, safe patient WS extensions, session/plan integration and restart tests | P7 frontend wiring, helper PIN unlock and real acceptance remain. |
| FR-62 | Export (CSV) and delete-everything; deletion completes within 24 h and is confirmed | Missing integration | store export_csv/delete_all helpers only | Authenticated complete export/delete endpoints, complete cleanup/confirmation; UI deletion is local only. |
| FR-63 | The word list accepts "my phrases" (kind = phrase, ≤ 60 characters), approved like words, practised in M2/M3, and exported as plain text in T6. No audio is recorded or stored | Partial | phrase schema <=60 characters; shared matching | Real phrase draft/approval, mode-specific practice and complete plain-text export. |
| FR-80 | Stroke-sign phrases stop the session and show the safety card with the local number (999 UK, 911 US, 1122 Pakistan); the linked carer gets a message within 10 s | Partial | terminal partial/final safety detection, localized number helper | Propagate person region (AppSession defaults UK); deliver linked-carer message <10 s. |
| FR-81 | Distress phrases (including short non-fluent ones) show the support card; carer told only if consented | Partial | distress rule + consent-gated carer_alerted boolean | Persist consent API; actual delivery with denial test when consent absent. Boolean is not notification. |
| FR-82 | Profile red flags (hoarse 3+ weeks, new adult stammer, choking, breathless, sudden hearing loss) show the right card; loudness practice pauses for hoarseness | Partial | red-flag rules and terminal cancellation tests | Actual voice/card acceptance; connect calibrated loudness pause to hoarseness flow. |
| FR-83 | Practice data is never used to infer a health change | Implemented locally | no diagnosis schema; constrained counts/templates | Review real agent tools/model outputs and submission wording; no inference of health changes. |
| FR-84 | AI_ENABLED=false switches every model line to templates without a redeploy | Implemented locally | Environment seeds DB once; PolicyLlm + per-attempt/nightly DB checks; dynamic switch tests | Verify selected DB/path and credit-free off behavior after GPU update; deployed acceptance remains. |
| FR-90 | Judge mode: three seeded demo people (Margaret: Finding words; Daniyal: Getting words out; Joseph: Being heard), a demo therapist login without MFA, a "simulate carer message" box, replay mode, and the live trace screen (J1) showing model IDs and latency | Partial | seeded personas, isolated judge-console tokens, browser event trace | Real model ID/latency trace, simulated carer path, consented scripted audio replay, fresh-browser walkthrough. |
| NFR-01 | Hint audio starts ≤ 300 ms (p95) after "yes" or Help; live reply first audio ≤ 1.0 s p50, ≤ 1.5 s p95 after the controller decides to speak | Unverified | live pipeline text call 0.764 s once; sentence TTS path | Hint first audio <=300 ms p95; reply <=1 s p50 /1.5 s p95 with enough real samples. Text time is not audio time. |
| NFR-02 | Found-word precision ≥ 0.95; recall ≥ 0.85 on the W set | Unverified | synthetic precision gate 1.0 | Volunteer W set: real ASR+boosting precision >=0.95 and recall >=0.85; evaluate per group. |
| NFR-03 | 0 interruptions for pauses ≤ 15 s; 0 sounds during blocks in Getting words out | Partial | synthetic pause/block gates and speech-reset tests | Real long pauses/stammer blocks, audible overlap count, VAD boundary and packet timing evidence. |
| NFR-04 | Judge walkthrough works from Oct 30 to Dec 15 12:00 PST; live voice 24/7 Dec 1–15; /healthz only green after a warm-up pass | Missing integration | healthz deliberately 503 voice_development, streaming_ready=false | Real warm-up/self-test before readiness; deploy uptime/monitoring for workbook judging window. |
| NFR-05 | Sessions per GPU measured in DR-6; session N+1 gets "The listener is busy, please try in a few minutes" | Partial | one GPU connection per process + busy rejection/cleanup tests | Measure sessions/GPU, required user-facing busy response; shared capacity/locks across workers. |
| NFR-06 | No audio, transcripts or diagnosis stored; logs and traces hold IDs and timings only; traces kept 14 days; weekly cards 12 weeks; consent records for the account's life + 2 years | Partial | no raw audio/transcript persistence in live adapter; redacted access logs | Phoenix spans IDs/timings only; audit detail text, trace privacy, 14-day/12-week/consent retention and deletion. |
| NFR-07 | TLS everywhere; session tokens valid 15 minutes, checked when the WebSocket connects (an open session continues), bound to one device; one live session per person; secrets only in env vars; OpenShell ≥ 0.0.34; PIPECAT_WEBSOCKET_AUTH=token ; no speaker embeddings | Partial | 15-min HMAC device tokens, expiry, local session registry, TLS guards | Production patient enrollment/auth, passkey/magic-link+MFA, trusted TLS proxy, shared locks, OpenShell deployment. |
| NFR-08 | Every MUST rule in the Design system | Unverified | UI components + browser regression tests | Frontend owner: full design MUST/A-set, axe, keyboard, 200% zoom and 320 px viewport on deployed flow. |
| NFR-09 | All screens, README, description and video pass the claims table | Unverified | LICENSE/NOTICE/README and practice-partner wording exist | Claims review all screens/docs/video; remove stale instructions and unsupported validation claims. |
| NFR-10 | Development ≤ $50 of GPU; judging ≤ $570 (live voice ≈ $525 + CPU ≤ $40); Token Factory within credits | Unverified | user limits paid calls; local GPU used | Cloud billing/cost alerts, budget and required uptime plan; no extrapolation from one model call. |

## Architecture and modes beyond the FR rows

- **D-02/03/07:** NeMo streaming and Silero are real. Parakeet EOU and Pipecat are not wired;
  listing them as optional dependencies/config does not implement them. Keep EOU advisory only.
- **D-04:** Magpie is real, sentence synthesis is real, but voice settings are not resolved:
  synthesize hardcodes speaker_index=0 instead of mapping TTS_VOICE=Aria. Verify the actual
  speaker map. Real clip cache, -20 LUFS normalization, WSOLA 0.8x and 500 ms hint gaps are open.
  mm is deferred by user preference, not removed from scope.
- **D-05/06:** Current adapter uses json_object/prompt instructions/think stripping. Strict
  schema/Instructor and real G-03 evidence remain open. Fallback must follow the workbook gate.
- **D-09/10/11:** No cloud deployment manifest, managed PostgreSQL adapter/migrations or saq
  worker exists in the inspected project. DATABASE_URL does not select the current SQLite app
  adapter. Scheduling depends on PostgreSQL eventually; it cannot be called complete beforehand.
- **D-12:** No carer agent/sandbox/tool runner or Telegram delivery implementation is present.
  OpenShell minimum-version configuration is not proof an actual sandbox has been installed.
- **D-13/14:** Custom scheduler, SequenceMatcher and custom phonetics are stand-ins. True FSRS,
  RapidFuzz/Jellyfish and CMUdict/epitran need adapters and representative tests. FSRS review
  helpers are not invoked by live attempt logging, and AppSession cycles all approved words
  instead of consuming the saved due-word plan.
- **D-15:** No wired OpenTelemetry/Phoenix spans or retention jobs. Add only IDs/timings, never
  prompt/audio/transcript bodies. J1 currently shows browser event summaries, not real model spans.
- **D-16/17:** Dataclass config/schema stand-ins remain; .env is not automatically loaded by
  current Settings. Reconcile workbook Pydantic/settings contract and preserve pure core.
  Validator coverage must include multiword phrases and template paths, not just generated lines.
- **M1-M5:** Current browser uses one generic cursor/prompt flow. Separate photo talk, daily
  chat, FSRS review, short day and fixed bank-call script. M3's target-only correction should not
  erase workbook M1/M2 plan-word recognition; make scope explicit with modes. M6/language packs
  are later and are not new v1 blockers.
- **Port cleanup:** app/audio.py still has an unused NotImplementedError and invalid
  nemo_toolkit import probe; the working server uses VoiceConnection/NemoStream instead.
  Remove/reconcile the obsolete path and the Asr/Tts protocol mismatch. It is no longer true
  that this unused scaffold prevents the current working browser voice path.
- **Session lifecycle:** default session_id is ws; propagate a unique session ID into attempts
  and traces. Rest currently changes presentation without explicit rest-state/timer suspension.
  Combined feedback modes choose one display; verify required combined-profile behavior.

## Work queue, in recommended order

These audit IDs are a new queue, not a renumbering of the earlier completed issues. A01/A02 have the local fixes recorded in the post-audit progress entries; GPU acceptance and full rest/settings integration remain open. Backend
owns implementation and API tests; frontend wires persisted controls; infrastructure owns
service provisioning/deployment. Real acceptance needs collaboration, not only Python tests.

| Order | Work item | Done when | Responsibility |
| --- | --- | --- | --- |
| A01 | Close practice correctness gaps | Being clear requires tap; full turn text accumulates/resets; session caps/no-limit/rest behavior tested. Start here, one fix per commit. | Backend/AI |
| A02 | Consistent AI policy and reply deadline | DB flag initial value and per-call nightly/live checks; dynamic switch; total budget and reason-bearing correction tests. | Backend/AI |
| A03 | Safe development persistence | File DB deliberate; seed once in judge/dev mode; restart preserves edits/deletion; unique session IDs. | Backend |
| A04 | Persisted console and patient settings APIs | Draft create/edit, role/PIN settings, consent, complete CSV/delete, denied access and restart tests; frontend can call documented endpoints. | Backend + frontend |
| A05 | Actual Being heard | Five calibration phrases, voiced PCM levels, captured DSP settings, threshold behavior and no numerical dB presentation. | Backend + frontend + GPU test |
| A06 | Finish practice modes and required adapters | M1-M5, real FSRS updating/plan consumption, matching libraries, pronunciation and EOU/Pipecat; mixed needs tested. | Backend/AI + frontend |
| A07 | Nightly plan/hint/clip production | Real Super/Instructor validation, per-call switch, rendered clips/voice verification/gaps/normalization, plan persistence and idempotent reruns. | Backend/AI |
| A08 | Carer tools and sandbox/channel | Linked carer message -> draft -> console link; counts only; consent-correct safety/weekly deliveries; G-05 proof/fallback. | Backend/AI + infrastructure |
| A09 | Real voice acceptance, health and telemetry | Latest Stop GPU test, overlaps, loud pauses, p50/p95 first audio, real W/P/N fixtures, capacity, warm health and privacy-safe spans. | Backend + infrastructure |
| A10 | Complete judge/submission flows | Synthetic carer box, real trace, consented replay assets, current README/setup, claims review, licences, feedback and video. | Backend + frontend + submission owner |
| A11 | Managed PostgreSQL and distributed jobs - deferred to end | Adapter/migrations, scoped restart persistence, shared locks, saq per-person 02:00 jobs and Friday 18:00 delivery, export/delete/retention acceptance. | Backend + infrastructure |
| A12 | Public Nebius deployment and final acceptance | HTTPS/WSS, auth/judge separation, endpoint gate, public repo/demo, uptime/cost/retention checks and full deployed workbook matrix. | Team |

A07/A08 can be built as local callable services before A11, but their actual scheduled
Postgres/saq delivery stays blocked on A11. Do not treat postponement as removal of a dependency.
Do not run large paid evaluations by default: agree a call budget and reuse synthetic tests;
real gated evidence is still necessary before claiming those gates passed.

## External evidence and submission checklist

| Gate | Current evidence | Remaining / allowed fallback |
| --- | --- | --- |
| G-01 | User says all access available | Keep actual billing/payment evidence privately; not independently audited. |
| G-02 | Local browser WebSocket works | Nebius 10-minute echo from PK/UK, RTT <200 ms. VM fallback only on documented gate failure. |
| G-03 | One accepted call per model; report false for full gate | 20/20 valid nonempty raw JSON per model, thinking off; explicit documented schema fallback if failed. |
| G-04 | Synthetic matcher tests only | 50 consented volunteer clips per demo profile, boosted precision/recall; threshold fallback per workbook. |
| G-05 | No implemented sandbox/carer evidence | Five consecutive scenario-8 passes; plain bot only after failed gate evidence. |
| G-06 | No blind listening results; mm deferred | Three listeners compare WSOLA; normal speed with gaps only if gate fails. |
| G-07 | No signed note in docs | Actual SLT review note if claiming review; omit claim otherwise. |

- [ ] Deploy on Nebius; keep full required judge availability, warm readiness and cost evidence.
- [ ] Public MIT repository; git remote/push/public visibility verified, correct NOTICE and assets.
- [ ] Required simulation/replay and fresh-browser README walkthrough, with no patient data.
- [ ] Real model IDs/latencies visible in judge evidence; performance gate results from real runs.
- [ ] Frontend accessibility/claims checks, 200% zoom, keyboard, target browsers and mobile widths.
- [ ] Privacy-safe telemetry, deletion/retention policies and jobs; actual authentication and TLS.
- [ ] Public video <=2:45 workbook target; description/Built With/Feedback, intended-use/system card,
  necessary releases/licences and submission confirmation. No public URLs or upload proven here.

## How to update this tracker

For each audit item append commit, exact tests, real/deployed evidence if relevant, and the
remaining failure. A unit test cannot close a cloud or acoustic acceptance requirement.
Keep sanitized evidence only. Never commit API keys, model payloads with person data or raw
patient audio. Current untracked token-factory-check.json remains outside this documentation
change and outside Git. No percentage or all-done claim is implied by this tracker.


## Progress after audit: Being clear tap-only policy

Implemented locally in the backend correctness checkpoint: a spoken yes cannot confirm a Being clear
word; check taps do, with strict boolean validation. New tests cover combined needs,
no success/advance before tap, rejection and duplicate taps, and preserved ordinary
hint/sound-alike confirmations. Full verification is now 223 backend tests passing,
with seven local synthetic release gates green. See BEING_CLEAR_CONFIRMATION.md.
A01 is partially complete; next: full current-turn transcript accumulation/reset,
then elapsed session cap/no-limit/rest behavior. No paid calls were made.


## Progress after audit: all four correctness fixes implemented locally

See BACKEND_FOUR_FIXES.md for the cumulative GPU bundle and test instructions.
Being clear tap-only success, whole current-turn ASR context, elapsed session caps
and consistent live/nightly database AI policy now have implementation and regression
coverage. Reply retries additionally share a single deadline and include rejection
reason. Verification: 244 backend tests, 11 browser tests and seven local synthetic
release gates pass; no model credits used. Changes are included in the backend correctness checkpoint. Latest
GPU acceptance is pending one cumulative update. Persistent settings/extension UI,
full rest UX, real acoustic/latency validation and larger integration tasks remain.
For an existing DB, use the switch CLI against the selected PL_DB_PATH to disable
paid calls; environment AI_ENABLED supplies only the first DB value by design.


## 22 October: authenticated draft creation

Added POST /api/console/words/{person} with strict input, linked-role access,
server-generated IDs and server-derived author role. New items remain drafts until
separate authorized approval and are excluded from practice. The existing phrase
Add control now saves through the API; failed saves never become browser-only live
entries. New audit creation rows use IDs instead of raw phrase text.

Verification: 255 backend tests, 14 browser tests, seven local synthetic gates pass;
no model credits used. File-backed restart and judge isolation tested. Live demo
acceptance is pending. See DRAFT_CREATION_API.md. This step does not implement cue
editing, saved profiles/settings, consent or export/deletion. Next: persisted profile
settings with role checks and the patient's right to lengthen/remove limits.

## 22 October: persistent profile settings

Implemented saved needs, waits, hint order and duration, with linked therapist/carer
permission rules. New sessions and nightly plans use stored profiles. Existing console
controls now PATCH the backend; failures do not create fake local settings. Patient
WebSocket extensions persist and can only lengthen/remove waits/caps, never change
protected needs/order. Getting words out's no-sound rule and Saving energy's turn cap
remain enforced. Saved overrides survive file-DB restart and are removed on deletion.

Verification: 271 backend tests, 17 browser tests, seven local synthetic release gates;
no paid model calls. See PROFILE_SETTINGS_API.md. Settings work is uncommitted. P7
frontend/PIN unlock remains open; patient protected changes are denied in the meantime.
Next: consent persistence, then nightly generation and Hermes tools, as previously agreed.


## 22 October: consent recording after profile settings commit

Profile settings committed as `649e72d`. Added authenticated consent PATCH,
strict explicit-person confirmation, independent distress/therapist-sharing and
practice-data choices, atomic latest state plus append-only consent events, and
console save/reload/error handling. See [CONSENT_API.md](CONSENT_API.md).

This is recording infrastructure: broad sharing/retention enforcement, P7 consent,
external alert delivery and account-life-plus-two-year retention remain open.
Do not mark NFR-06 or complete consent compliance as done. Export/delete UI remains
unfinished. On-demand nightly generation and Hermes are still next planned work.

Validation: 276 backend tests and 20 browser tests pass; all seven local
synthetic release gates are green. No paid model calls were made.


## 22 October: on-demand plan preparation and live consumption

Committed model logging/grounding as `efd1e44` before implementing this step.
Added authenticated POST /api/console/plans/{person}/generate and the local
`patient_listener.tools.generate_plan` command. Default one approved word, no
paid calls; explicit use_ai permits at most one Super attempt per selected word.
Saved plan subset/order/prompts now drive new sessions. Three Magpie hint clips
per word are cached in the database and reused with normal playback ACKs. Atomic
publication preserves the prior plan on failure. Existing demo word rows/hints
survive restart seeding. See [ON_DEMAND_PLANS.md](ON_DEMAND_PLANS.md).

Validation: full suite of 299 backend tests and 20 browser tests passed, followed
by the expanded 16-test generation suite (two additional cases, 301 backend tests
in total). Seven local synthetic release gates pass. Fake models only; no paid
requests or GPU rendering was run here. Real GPU acceptance is still pending.

This is manual generation only. Scheduled nightly deployment, separate render
service, full FSRS, Instructor, audio normalisation/voice acceptance, weekly
delivery, Hermes and shared-worker coordination remain open.
