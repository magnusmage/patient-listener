# Patient Listener - frontend integration handoff

Updated: 26 October 2026. Audience: frontend developers and QA.

## 1. Scope, source of truth and starting code

Build against Patient Listener Workbook v1.html, particularly Screens, Design system,
Functional requirements and evaluation scenarios. Ask the backend owner for the
workbook HTML; it is not included in this handoff. Use "AI practice partner" wording;
do not describe the app as treatment, assessment or health monitoring.

Repository: https://github.com/magnusmage/patient-listener
Latest committed local baseline: `b48578c` (GPU container milestone).
Previous service split: `cda5077`. The backend owner must confirm these commits are
available remotely before you start. A local commit is not necessarily pushed.

This handoff accompanies a subsequent local backend checkpoint for precise silence
deadlines, rest/resume and synthetic GPU warm-up. These changes are not part of
b48578c. Obtain the new checkpoint revision from the backend owner and confirm it
is shared; GPU warm-up and rest/resume acceptance remain incomplete. No frontend
redesign is bundled with these changes.

Existing UI files are integration references, not a finished compliant product:
- `web/app.js`: patient screens, events, captions, controls.
- `web/client.js`: LiveDriver, ServerDriver, device ID and audio protocol.
- `web/worklet.js`: native-rate microphone downsampling to 16 kHz.
- `web/console.html`: inline helper-console implementation, authenticated reads,
  draft/approval/settings/consent wiring and remaining demo-only privacy behavior.
- `web/tokens.css` and `web/app.css`: current visual foundation.
- `tests/console_auth_web.test.cjs`, `tests/safety_stop_web.test.cjs`,
  `tests/voice_playback_web.test.cjs`: existing browser contract checks.

The current frontend is plain HTML/CSS/JavaScript; no frontend npm build is required
for the existing pages. Normally the backend serves web/ on the API origin. If you
introduce a separate development server/framework, agree the proxy and routing
contract first; opening index.html through file:// is not a live API setup.

Reuse the transport/controller boundary. The backend decides turn timing, hint
eligibility, word matches, found status, safety and approval permissions. The UI
must not independently mark words found, approve drafts or run a competing patience
controller in live mode. Offline sample mode must remain explicitly labelled.

## 2. Connection worksheet - obtain from the backend owner

| Detail | Current local setup / action needed |
|---|---|
| Shared code revision | Confirm actual pushed commit or supplied source bundle |
| Reachable API origin | Pending: backend owner supplies a URL reachable from your machine |
| API documentation | `<API_ORIGIN>/docs` |
| OpenAPI JSON | `<API_ORIGIN>/openapi.json` |
| Patient page | `<API_ORIGIN>/?voice=1` |
| Helper console | `<API_ORIGIN>/console.html` |
| Frontend origin | Send your exact scheme/hostname/port to backend owner |
| Public voice WebSocket | Obtain through session API; do not hardcode port 8001 in deployed UI |
| Test therapist/carer access | Request separate privately supplied tokens and linked test patient IDs |
| Dedicated deletion fixture | Request a disposable patient, not a shared demo/person record |
| Supported test browsers | Coordinate Chrome/Edge, Safari and mobile coverage |

127.0.0.1 refers to the computer running YOUR browser. It cannot reach somebody
else's GPU machine. Cloud hostnames, shared access and production login URLs are
not yet provisioned; none are invented here.

Prefer same-origin frontend and API hosting, including a development reverse proxy
if needed. The current API does not provide a general cross-origin CORS setup.
A separate frontend port/domain needs an agreed proxy/CORS/cookie configuration.
`credentials: "include"` alone does not override SameSite restrictions. Do not
switch casually between localhost and127.0.0.1: browser storage and cookie matching
differ. Cloud UI uses HTTPS and the voice URL uses WSS.

The CPU/API service owns frontend files, auth/enrollment, REST APIs and session
issuance. The GPU service owns live voice and private rendering. Browser code must
never call `/internal/render` or receive its service key. GPU WebSocket admission
requires an exact allowed Origin; tell backend the actual frontend origin.

## 3. Priorities and delivery slices

| Priority | Work item | Done when |
|---|---|---|
| P0 | Device setup/enrollment and revocation | Fresh browser can enroll without DevTools; revoked browser cannot start a new session |
| P0 | Session lifecycle and error screens | One Start creates one connection; errors/busy/unauthorized differ from successful completion |
| P0 | Real CSV and deletion flow | Uses authenticated backend, separate confirmation and actual receipt; no mock success |
| P0 | Patient extend/off settings | Sends server controls; no PIN for lengthening/disabling; invalid changes surface errors |
| P1 | Role-aware console completion | Linked caseload, drafts/approval/settings/consent survive reload and obey permissions |
| P1 | Plan preparation/status | Authenticated preparation, disabled duplicate submit, meaningful results and failure states |
| P1 | Profile practice/rest/safety UI | All profile-specific controls, captions, Stop, calibration and terminal safety states work |
| P1 | Progress/accessibility/judge walkthrough | Server data, fixed symbols, accessible layout and clearly isolated sample/judge states |

Enrollment, export/deletion and connection errors are the best first parallel tasks.
Do not rebuild flows that are already wired without checking existing behavior.

## 4. Authentication and linked-person permissions

### Helper console

Currently use a provisioned opaque bearer token, not the Nebius API key:

```http
Authorization: Bearer <HELPER_ACCESS_TOKEN>
```

Backend owner provisions separate therapist and carer test tokens privately. CLI
provisioning defaults to 8 hours, configurable. Request replacements when expired.
Do not put tokens in source, query strings, screenshots, analytics or error reports.
Keep console tokens in memory and clear patient state on logout or authentication
failure. Do not store them in localStorage. Current UI uses memory-only token state.

| Method/path | Request | Response/use |
|---|---|---|
| GET `/api/console/me` | Bearer header | `{id,name,role,demo}`; use server identity, never a client role selector |
| POST `/api/console/logout` | Bearer header | `{ok:true}`; revokes the presented token; clear local state too |
| GET `/api/console/caseload` | Bearer header | `{therapist:{name},caseload:[{id,name,needs,last,returned,canApprove}]}` |
| POST `/api/console/demo/session` | No helper token | `{token,demo:true}` only when demo console is enabled; otherwise404 |

A carer can add drafts. A linked therapist approves and edits profiles. A linked
carer can approve/edit only if NO therapist is linked to that person. Use
`canApprove` from caseload and `canEdit` from settings for rendering; backend403 is
still authoritative. Detailed progress is therapist-only. Do not fetch the grid
for carers and then hide it.

Judge-demo tokens use a separate console store, expire after 1 hour and cannot
perform real enrollment or privacy operations. There is no complete isolated judge
voice enrollment flow yet; do not pass judge tokens as real helper credentials.

Production magic links, passkeys/MFA and helper PIN verification are PENDING backend
contracts. A client-only PIN is not authentication. Do not fabricate these endpoints
or represent today's bearer-token sign-in as finished production identity.

### Patient device identity and enrollment (APIs ready)

The patient does not enter a helper token. A linked helper initiates setup, and the
patient browser redeems a single-use code. Keep the helper credential in the helper
context. Do not put the setup code into a URL, analytics or logs.

Generate one cryptographically random device ID and reuse it for enrollment, session
requests and WebSocket connections. Existing localStorage key:
`patient-listener-device-id`. Allowed identifier: 32-128 ASCII letters/digits/`_-.`.
The current client generates 24 random bytes encoded as 48 hex characters. The device
ID is an identifier, not the authentication secret. Do not regenerate it on Start.

1. Linked helper creates setup code:

```http
POST /api/console/patients/margaret/device-links
Authorization: Bearer <HELPER_ACCESS_TOKEN>
```

Response fields: `person_id`, `setup_code`, `expires_at`. Code expires after 10 minutes;
a new code supersedes the previous code from that helper for that person.

2. Target patient browser redeems it, on the API origin:

```javascript
const response = await fetch('/api/patient/enroll', {
  method: 'POST',
  credentials: 'same-origin',
  headers: {'Content-Type': 'application/json', 'X-PL-Device': deviceId},
  body: JSON.stringify({setup_code: setupCode})
});
```

Success: `{linked:true,person_id,authorization_id,expires_at}`. Browser receives
`pl_patient_link`, an HttpOnly, SameSite=Strict cookie scoped to `/api/session`,
Secure when HTTPS is required. JS cannot and must not read/copy the cookie. The
persistent device credential is never returned in JSON. Successful redemption is
single-use; replay/expired/invalid code returns400. Browser enrollment lasts up to
365 days unless revoked/relinked/deleted. Keep setup inputs out of persistent storage.

3. Device management, linked helper bearer required:

| Method/path | Result |
|---|---|
| GET `/api/console/patients/{person}/devices` | `{devices:[{authorization_id,created_at,expires_at}]}` |
| DELETE `/api/console/patients/{person}/devices/{authorization_id}` | `{revoked:true}` when removed |

Revocation prevents new token issuance and new WebSocket admission. It does not
currently force-close an already established practice session. Explain that accurately.
The CLI enrollment checker creates and revokes its OWN temporary device; it does
not enroll a real user's browser.

## 5. Patient session and voice transport

`{person}` accepts a server-provided caseload ID, e.g. `margaret` or`demo-margaret`.
Do not derive patient access from whichever profile card is selected. Existing
persona shortcuts are demo behavior; real person selection comes from an authorized
workflow. Do not assume aliases exist for every production patient.

After Start, request the session using the SAME device ID and enrollment cookie:

```javascript
const response = await fetch(
  `/api/session?person=${encodeURIComponent(person)}&voice=true`,
  {headers: {'X-PL-Device': deviceId}, credentials: 'same-origin', cache: 'no-store'}
);
```

Response shape:

```json
{
  "ws_url": "<PUBLIC_VOICE_WS_URL>",
  "token": "<SHORT_LIVED_SESSION_TOKEN>",
  "person": "margaret",
  "needs": ["finding_words"],
  "voice_enabled": true
}
```

Connect to returned `ws_url`, appending URL-encoded `token`, `device` and`voice=true`.
Use the existing LiveDriver code for correct query joining. Session tokens are
valid 15 minutes in production, checked on connection; an already open session can
continue after token expiry. Obtain a new token for a NEW connection. Do not log
WebSocket URLs, persist session tokens, automatically reconnect indefinitely or
open multiple sockets while Start is pending.

Omit`voice=true` for the existing text WebSocket path on the CPU API. Text mode is
backend-driven without microphone audio; do not present it as live GPU voice.
`voice_enabled:true` is a capability indication, not confirmation the GPU is free
or operational. API health can be200 while remote GPU is unavailable.

### Existing audio protocol: preserve it

- Plain WebSocket plus AudioWorklet; no new browser voice SDK is required.
- Microphone opens only after Start. Capture native rate and downsample in worklet
  to mono 16 kHz PCM16 little-endian binary frames. Maximum frame size32768bytes,
  even length. Do not send MediaRecorder WebM/Opus blobs.
- Receive mono 22050 Hz PCM16LE. Set`binaryType='arraybuffer'`.
- Server sends`audioStart` with`id`, `sample_rate:22050`, `encoding:'pcm_s16le'`,
  then binary PCM and`audioEnd` with matching`id`.
- Send`{"type":"playback_done","id":<id>}` ONLY after actual playback finishes,
  not just on receipt of`audioEnd`. Otherwise turn advancement can overlap speech.
- `audioCancel`: immediately discard old output, suppress its stale acknowledgments
  and keep the session alive. `audioIdle`: output drained/listening may resume.
- During app playback the server ignores practice speech except spoken Stop. Do
  not disable the microphone path needed to recognize Stop, and do not route the
  listener's audio back into practice matching.
- Stop must cancel local audio immediately, send`stop` when possible, release tracks,
  close the socket and audio context, and ignore late events/audio. Do not wait for
  a backend response before stopping sound. Backend timing still needs measurement.
- `voiceNotice` may explain missing prepared hint audio; show it without pretending
  sound played. `voiceError` ends transport and needs an error screen, not a success.

### Browser-to-server controls

All controls are JSON text frames; microphone audio is binary.

| Control | JSON example / purpose |
|---|---|
| Start | `{"type":"start"}` after socket opens |
| Typed answer | `{"type":"typed","text":"synthetic practice answer"}` |
| Help | `{"type":"help"}` |
| Hint/confirmation answer | `{"type":"yes"}` or`{"type":"no"}` |
| Being-clear check | `{"type":"confirm_tap","ok":true}` (or false) |
| Words-out Done | `{"type":"done"}` |
| Rest / resume | `{"type":"rest"}` /`{"type":"resume"}` |
| Stop | `{"type":"stop"}` |
| Accept calibration phrase | `{"type":"calibration_next"}` |
| Skip unsupported calibration | `{"type":"calibration_skip"}` |
| Extend session/off | `{"type":"extend_session","minutes":30}` or minutes:null |
| Extend waits/off | `{"type":"extend_settings","max_wait_s":30}`; use null to disable a wait |
| Playback ACK | `{"type":"playback_done","id":1}` after playback |

`audio_settings` carries actual mic-processing booleans/null values:
`auto_gain_control`, `noise_suppression`, `echo_cancellation`, `safari`, `changed`.
Use the existing client's reporting logic; do not infer support just because a
constraint was requested. Calibration controls require the current phrase to have
enough voiced audio. Never derive loudness from typed words or guessed values.

### Server events and UI behavior

| Event | UI responsibility |
|---|---|
| greeting / prompt | Show supplied text/caption; prompt also supplies profile,feedback,topic,photo and optional calibration/instruction |
| caption | Show transient recognized text; partial:true updates the partial caption without persistence |
| state | Update listening/speaking/resting state from server |
| backchannel | Caption the supplied listening sound |
| offerHint | Offer Help/Yes/No; do not automatically advance hints |
| hint | Display supplied text/letter appropriately; never reveal target early |
| confirm / whatIHeard | Show confirmation; Being-clear requires the check tap |
| found / attempt | Display server result; do not calculate a match or write attempts in the browser |
| reply / moveOn | Display corresponding caption; follow transport audio events |
| restOffer | Show Rest screen and Keep going/Stop; do not auto-resume |
| calibrationReady / loudness | Enable phrase acceptance or show qualitative feedback; never show dB/numeric level |
| settingsSaved | Acknowledge persisted patient extension/off change |
| safety | Stop output/capture and show the supplied terminal card; never overwrite with generic End |
| ended | Show true completion reason (`stop`,`done`,`turn_cap`,`session_cap`, etc.) |
| voiceError | Display failure using code; release transport, preserve error state |
| voiceNotice | Display factual audio availability message |

Safety payload includes`card`, `title`, `body`, `number` as applicable. Do not infer
that a carer was actually notified: delivery integration is still pending. Person
region propagation is also pending; do not silently hardcode UK emergency wording
for everyone. Coordinate approved localized cards with backend/workbook owner.

Hint`level` currently reflects semantic enum 1=meaning / 2=sound / 3=word. With sound-first
settings it is not necessarily the ordinal step number. Coordinate an explicit
hint-type/position contract before assuming the UI can always say"Hint1of3".
Some current prompt placeholders contain target text; the no-early-reveal audit is
still open. Flag these for backend correction rather than rendering target-bearing
placeholder fields as patient-facing answers.

## 6. Words, phrases and approval

Bearer header on all helper APIs.

| Method/path | Contract |
|---|---|
| GET `/api/console/words/{person}` | `{person,words:[{id,text,kind,cue,first,status,by}]}` |
| POST `/api/console/words/{person}` | Creates a draft;201 with`{ok:true,word:{...}}` |
| POST `/api/console/words/{person}/{word_id}/approve` | Allowed approver only;`{ok:true,word:{...}}` |

Draft request (synthetic example):

```json
{"text":"Milo","kind":"person","meaning_cue":"a family pet","first_sound":"M"}
```

Allowed kinds:`person`,`place`,`food`,`object`,`activity`,`phrase`.
`text`:1-60 characters;`meaning_cue`:<=90;`first_sound`:<=4, optional/derived when blank.
Inputs are single-line without control characters. Phrases use`kind:"phrase"` and
the same<=60limit. Client must NOT send actor, role, status, approval identity or
person_id in the body: server derives identity and person from authentication/path.

Display draft/approved/retired states truthfully. New entries are drafts even when
added by a therapist; approval is a separate action. Show success only after the
server responds. Preserve form input on422/503, and refresh the saved list afterward.
There is currently NO word/cue PATCH endpoint, retire/delete-word endpoint or photo
upload endpoint. Existing editable-looking cue inputs do not imply a working save
contract. Request backend endpoints before promising editing/photo features.

## 7. Helper profile settings and patient controls

GET/PATCH`/api/console/settings/{person}`. GET fields include`needKeys`,`needs`
(display labels),`hintOrder`,`hintWait`,`backchannelWait`,`maxWait`,`sessionMin`,
`canEdit` and`values`. Use`values` for the canonical snake_case fields.

The five setup choices are backend keys:
`finding_words`,`words_out`,`being_heard`,`being_clear`,`saving_energy`.
Needs can be combined. Do not expose diagnosis entry or treat the legacy`listening`
label as a sixth selectable setup need.

Example helper PATCH (send only changed fields):

```json
{"max_wait_s":30,"hint_order":["sound","meaning","word"]}
```

| Field | Accepted value |
|---|---|
| needs | Nonempty unique array of the five keys above |
| hint_order | `["meaning","sound","word"]` or`["sound","meaning","word"]` |
| backchannel_s |2-15seconds, or null/off |
| offer_hint_s |4-15seconds, or null/off |
| max_wait_s |8-120seconds, or null/off |
| max_session_min | Integer 3-120 minutes, or null/off |

Null switches a wait/cap off; omission leaves it unchanged. Zero/empty strings are
not equivalent. Backend applies merged-profile rules and may reject combinations.
Words-out must keep backchannels and hint offers off. Re-render returned settings
only after successful save. Helper changes apply to new sessions.

Patient P7 can always LENGTHEN or switch off a wait/cap without a PIN. It cannot
shorten, re-enable an already disabled wait, change needs/hint order or consent.
Use`extend_settings`/`extend_session` on the enrolled live connection. Backend will
reject unauthorized shortening. A complete patient-specific HTTP settings-read
contract is not currently exposed; coordinate initial P7 values with backend.

Profile UI checks: Words-out has no Help/listening sound and has Done; Being-clear
has a real check tap; Being-heard has five-phrase calibration; Saving-energy has
Rest/Resume,15 turn cap and 10 min default session cap. Don't implement these decisions
with independent client timers. Follow workbook merged-profile rules for combined needs.

## 8. Consent, CSV export and deletion

GET/PATCH`/api/console/consent/{person}`. Fields:
`tellCarerLowMood`,`dataSharing`,`shareWithTherapist`.
PATCH requires explicit confirmation of the PERSON'S choice:

```json
{"personConfirmed":true,"tellCarerLowMood":false}
```

Never initialize missing consent to true or silently attach confirmation to a
choice the person has not made. Production PIN flow is pending; do not fake it.

### CSV

POST`/api/console/privacy/{person}/export` with bearer and:

```json
{"personConfirmed":true}
```

Response is a CSV attachment, NOT JSON. Download the returned Blob; honor its
filename or use a safe fixed filename. Do not recreate export from the visible
word list: backend export includes additional records and CSV injection protection.
This is an assisted person-requested operation, not unrestricted carer progress access.

### Two-step deletion

1. POST`/api/console/privacy/{person}/deletion-request`, bearer, no body required.
   Response:`person_id`,`confirmation_token`,`expires_at`,`message`,`retained_records`.
   The confirmation token expires in 10 minutes; keep it only in memory.
2. Show a separate confirmation screen with the person's identity and the supplied
   retention explanation. Cancellation must not issue DELETE.
3. DELETE`/api/console/privacy/{person}` with bearer and JSON body:

```json
{"personConfirmed":true,"confirmationToken":"<TOKEN_FROM_DELETION_REQUEST>"}
```

Note the spelling: response`confirmation_token` -> request`confirmationToken`.
4. Display returned`deleted`,`receipt_id`,`completed_at`, and retention fields.
   Query GET`/api/console/deletions/{receipt_id}` with the same helper identity to
   re-check its receipt. Clear the deleted person's UI cache and selection.

Do not claim completion on409/503. Stop active practice/plan work first. Repeated
confirmation of a completed deletion can return the existing receipt; after network
uncertainty query the receipt when known rather than inventing success. Export and
deletion reject judge-demo credentials. External photo/object deletion can block
completion until its backend adapter exists; do not promise that unfinished integration.
Use ONLY a dedicated disposable record supplied by backend for deletion acceptance.

## 9. Plan preparation, nightly status and progress

POST`/api/console/plans/{person}/generate`, allowed profile manager bearer:

```json
{"max_words":4,"use_ai":false,"render_audio":true}
```

`max_words`:1-10, an upper bound, not a promise of exactly that many words.
Default`use_ai:false` avoids Token Factory calls;`render_audio:true` needs available
GPU rendering. Request runs to completion; there is no asynchronous job-ID/polling
API for this manual action yet. It replaces the saved plan and is not read-only.
Disable duplicate clicks and retain pending state. Do not automatically retry a
paid generation request after network uncertainty. Coordinate HTTP timeouts with
backend; generating several clips can take time.

Response:

```json
{"person_id":"demo-margaret","plan_items":2,"model_attempts":0,
 "model_hints":0,"template_hints":2,"rendered_clips":6,
 "word_ids":["w-kettle","w-whitby"]}
```

Show actual result counts. Zero-model calls does not mean GPU rendering failed.
A fresh practice session picks up the new plan. Previous plan is kept on generation
failure.409means active practice/GPU busy or plan conflict;403means permission/AI
policy rejection;503means service/rendering failure. End practice before preparing.

GET`/api/console/nightly/{person}` exposes:
`enabled`,`time`,`timezone`,`max_words`,`use_ai`,`saved_ai_enabled`,`render_audio`,
`scheduled_for_person`,`actor_authorized`,`daily_model_limit`,`runs`.
It describes the current DEVELOPMENT scheduler; durable saq/Serverless dispatch,
per-person schedules and Friday delivery are pending. No schedule-edit endpoint,
weekly-card read endpoint or browser AI-switch endpoint is currently exposed.
Do not build UI success claims around those absent APIs.

GET`/api/console/grid/{person}` is therapist-only:
`{person,days:[...],rows:[{word,cells:[...]}]}`.
Map codes:`check`->✓,`meaning`->M,`sound`->S,`word`->W,`none`->–.
Use accessible text labels, not color alone. Show counts/what happened, never
clinical improvement/predictions. Current day buckets are UTC and hint-order
semantics still need backend correction; do not independently manufacture local
calendar data or infer recovery from this grid.

## 10. Error handling and readiness

REST errors may use`{"detail":"..."}`, a422validation-detail array, or session
`{"error":"..."}`. Treat response status as authoritative and render errors safely
as text. Do not inject backend/user/model strings through innerHTML.

| Status | Frontend action |
|---|---|
|400 | Show safe validation/setup error; expired/reused code needs a fresh setup code |
|401 | Helper token invalid/expired -> sign in; session401 -> patient device setup required |
|403 | Permission denied; do not change local role or silently retry |
|404 | Not found/inaccessible/demo disabled; do not enumerate other patients |
|409 | Active practice/GPU/plan conflict; explain and allow deliberate retry after resolution |
|422 | Show field errors; preserve unsaved input; no fake local success |
|503 | Service unavailable or operation unconfirmed; retain error state |

Pre-accept WebSocket rejections can appear as HTTP403 in server logs and an opaque
browser connection failure. Browser APIs may not expose the HTTP body or intended
close reason. Do not assume every rejected socket means expired enrollment or
silently start another session. A richer admission-error contract is backend work.
Accepted-connection close codes may include1000normal,1008policy,1011failure,
1013busy/admission loss. Preserve an explicit safety/ended/voiceError event over a
subsequent generic socket close. A close alone is not proof of successful practice.

`/livez` is process liveness only. In committed baseline b48578c voice`/healthz`
intentionally returns503`voice_development`. The backend readiness update changes
it to200`voice_ready` after synthetic inference warm-up; reports`warmup_passed` and
`production_acceptance_verified:false`. Neither liveness nor warm-up proves all
workbook latency/accuracy/capacity gates. API`text_ready` does not check remote GPU.

## 11. Accessibility, privacy and claims

Follow every MUST in the workbook Design system: readable fonts/spacing, large
controls, contrast, visible focus, keyboard navigation, screen-reader labels and
clear status text. Use the workbook's exact numeric design tokens; this document
does not replace them. Avoid conveying listening, progress or errors by color alone.

All spoken paths need captions, including prompts, hints and confirmations. Keep
captions transient; never send transcripts, microphone audio, word lists, consent,
credentials or model responses into browser analytics/session-replay tools. Do not
persist raw audio/transcripts in localStorage, IndexedDB, service-worker caches,
error reporting or recordings. Live audio is transient. Backend-produced hint clips
are synthesized content, not patient recordings.

No target reveal before the allowed hint level. No numeric loudness feedback.
No diagnosis forms, medical predictions or claim of notification delivery without
confirmation. Safety is terminal and must win over late audio or success animations.
Keep Stop available throughout connecting/playback/rest. Verify frontend cancellation
latency; backend tests are not a browser performance measurement.

## 12. Hermes and other backend dependencies

Frontend contribution to Hermes: console links must open the correct authorized
patient's draft word list, or preserve that destination through helper sign-in.
The existing agent returns`console_path:'/console.html'`; a patient/word deep-link
contract is not finalized. Agree routing with backend instead of assuming query
parameters are implemented. Do not expose agent credentials or build a second
unscoped chat-to-approval API. Hermes can draft; only the authorized human approves.

Backend-owned pending work includes real Hermes/OpenShell/NemoClaw/Telegram,
carer notification delivery, per-person region/timezone, durable jobs/cards,
production identity/PIN, explicit modes/photo storage, judge trace/replay and
performance instrumentation. Frontend may build clearly labelled scaffolding, but
must not present simulated delivery/security/data persistence as completed behavior.

## 13. Acceptance checklist to return with frontend work

- [ ] Share tested frontend/API revisions and exact browser/origins.
- [ ] Fresh browser completes setup without DevTools; setup code cannot be reused.
- [ ] Revoked device cannot start a NEW session; active-session limitation documented.
- [ ] No mic before Start; one pending Start/one socket; cleanup after failure and Stop.
- [ ] Voice uses returned GPU URL; text path stays on API; no private render access.
- [ ] Unauthorized, busy, network failure, safety and normal end have distinct states.
- [ ] Actual PCM playback ACK; audioCancel and Stop discard stale output.
- [ ] All spoken paths captioned; typed answers remain usable; no transcript persistence.
- [ ] Words-out, calibration, Being-clear check and Saving-energy Rest/Resume tested.
- [ ] Automatic rests do not skip words or count an extra turn on the updated backend.
- [ ] Helper roles/drafts/approval obey backend flags and survive reload.
- [ ] Profile and consent edits use real APIs; patient extend/off has no PIN gate.
- [ ] CSV comes from backend; deletion uses separate confirmation and real receipt.
- [ ] Failed saves preserve input and never mutate live data only in browser memory.
- [ ] Plan preparation shows actual selected count; no duplicate submits/paid auto-retries.
- [ ] Progress symbols, accessibility/keyboard/mobile and safety terminal state verified.
- [ ] Remaining backend blockers are listed explicitly in the PR; no invented APIs.

For each slice provide screens changed, endpoints used, test fixture/role, observed
requests/results and unresolved backend questions. Never include secrets, full WS
URLs, actual patient transcripts or recordings in screenshots/test reports.

## 14. First session with the backend owner

Obtain the reachable API URL, matching code revision, disposable linked patient,
therapist/carer tokens and exact allowed frontend origin. Open`/docs` and verify
GET`/api/console/me` for each credential. Implement helper-generated setup and
patient-browser redemption first, then test one enrolled session with AI disabled.
Keep the model-call budget under backend control. GPU/cloud provisioning and
Token Factory keys are not required frontend tasks.
