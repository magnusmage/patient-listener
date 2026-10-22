# On-demand plan generation

Implemented 22 October 2026, following the model logging/grounding commit `efd1e44`.
This is the manually triggered preparation path, not a scheduled nightly deployment.

## What is connected

`POST /api/console/plans/{person}/generate` accepts a strict JSON object:

```json
{"max_words": 1, "use_ai": false, "render_audio": true}
```

Defaults: one word, no paid model calls, three local GPU hint clips. `max_words` is
1..10; unknown fields and coerced strings/booleans are rejected. An authenticated
linked therapist, or linked carer when no therapist is linked, can request it.
Agents and unlinked helpers cannot. Judge demo supports only templates/text and
uses its isolated store. The endpoint responds after generation finishes, with
counts and word IDs; it does not launch a detached/background job.

The builder filters approved words, applies the existing due-card helper and
falls back to the previous approved plan when nothing is due. Obsolete cards are
removed from consideration before the word limit is applied. No draft is approved
or selected by generation. This still uses the project's existing simplified FSRS
implementation; full FSRS and live review updates remain open.

When use_ai=true and the saved AI switch is on, Super receives only that word's
fact record. Each selected word gets at most one Super attempt with a ten-second
budget, no retry. Invalid/missing/failed meaning hints use templates. Template
cues are checked against the same meaning-reveal/length rules; unsafe cues get a
neutral hint. Sound and word lines are code templates. Existing hint validation
is rule-based; semantic correctness still needs acceptance review.

The running server reuses its already-loaded Magpie model, under the GPU lock,
for three mono PCM16 / 22.05 kHz hint clips per selected word. Empty, malformed or
longer-than-20-second clips fail generation. This does not yet implement workbook
loudness normalisation, WSOLA, voice mapping verification, or generic clip caching.
No patient recordings or transcripts are stored: hint_audio contains synthesized
hint lines only, scoped by person, word, level, exact text, voice and model.

Hints, clips, plan and an ID-only audit event publish in one transaction. If TTS
or the publication fails, the prior published plan/hints/clips remain. Roles,
links and approved word content are checked again before publication. If AI is
switched off while model-authored hints are being rendered, generation aborts;
retry without use_ai. If switched off before a model response is selected, a
template is used. Admission is shared with active patient sessions and the GPU
voice slot, so stop the active browser session before generating.

New AppSession instances snapshot the saved approved subset/order and prompts.
Cached hints bypass live Magpie synthesis but use the existing playback ACK,
half-duplex and Stop/safety controls. Missing or mismatched clips use live TTS.
Changes apply to new sessions. Existing session cycling, rest UX and session caps
are unchanged. Restart seeding now preserves existing word rows and generated
hints instead of overwriting them. Deletion removes cached hint audio too.

## GPU test: no paid calls

Copy this update into ~/patient-listener-voice/project with the directory structure
preserved. Stop/restart the server after copying; do not replace pl.db, the sibling
.venv, or API keys. Keep VOICE_ENABLED=true and PL_DB_PATH pointing to your file DB.

Stop the current browser practice session. Keep the server running. In a second
terminal, activate the same environment:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m patient_listener.tools.generate_plan --person margaret --max-words 1
```

Paste a linked therapist console token at the hidden prompt, not the Nebius key.
Expect plan_items=1, model_attempts=0, rendered_clips=3. This call runs local Magpie
only. Open a NEW practice session, request hints and check captions/audio. Turn
AI off with tools.switch first if the practice session itself must use no paid
Lightning calls; generation's use_ai flag does not alter the global switch.

For text-only testing without a GPU:

```bash
python -m patient_listener.tools.generate_plan --person margaret --max-words 1 --text-only
```

## Optional one-request Super test

Only after the no-credit test succeeds, enable the saved AI switch and ensure the
server was started with NEBIUS_API_KEY and the openai SDK installed. Then:

```bash
python -m patient_listener.tools.generate_plan --person margaret --max-words 1 --use-ai
```

This opts into at most one Super request. The response reports model_attempts,
model_hints and template_hints. Token Factory logs distinguish response, error and
cancellation, without printing facts, response text or credentials. A timeout can
still incur provider charges. MAX_LIGHTNING_CALLS limits live Lightning calls,
not Super; max_words bounds this generation request. Repeating the command is a
new request and may spend again. Disable the saved AI switch after testing.

## Still remaining

Automatic nightly scheduling, durable queue/retry coordination, an internal render
service for separate CPU jobs, Instructor, full FSRS integration, weekly delivery,
Hermes/OpenShell and production Postgres/SAQ remain. Admission is process-local;
multiple workers/hosts need shared coordination. This route is a development
step toward workbook FR-41, not proof that all nightly requirements are complete.
