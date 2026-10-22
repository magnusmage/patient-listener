# Four backend correctness fixes: one GPU update

21 October 2026. Builds on the committed browser voice prototype at c928b1f and
includes the earlier Being clear update. Apply this bundle once; do not apply the
individual Being clear zip as an additional step. Included in the backend correctness checkpoint; see Git history.

## What is fixed

1. **Being clear (FR-14):** a matched word remains pending until confirm_tap(true).
   Spoken yes cannot log success, praise, reply or advance. A rejecting tap clears
   the match; duplicate taps cannot log twice. Hint offers and Finding words
   sound-alike confirmations can still accept yes. Confirmation payloads must be
   actual booleans, not strings/numbers.
2. **Current answer (FR-12):** finalized ASR segments accumulate in transient
   turn_text. The completeness decision and Getting words out reply receive the
   whole current answer; other profiles send at most its most recent 20 words.
   A typed answer replaces the text so corrections are possible. Partial captions
   are not appended as final segments. New prompts, Stop and safety clear context.
   Safety checks can detect a phrase split across finalized/partial segments.
3. **Duration cap (FR-07):** a monotonic session timer enforces the merged profile
   cap, including time spent resting. Repeated Start cannot reset the clock.
   Expiry/turn cap cancels queued practice audio, speaks Well done today, waits for
   playback completion, then ends. Stop can interrupt the closing line. Stop,
   disconnect and safety cancel the cap task. No limit disables the timer.
4. **AI switch (FR-84):** AI_ENABLED seeds a new database flag once. Restart does
   not overwrite a saved operator switch. Runtime adapters recheck the DB before
   every reply/plan/completeness call and discard a result if switched off during
   the call. The existing session can switch off -> on without reconnecting if
   credentials/SDK were available when constructed. Nightly processing checks each
   word independently. AI off means templates and keep waiting for completeness;
   Done remains available. ASR/TTS continue locally; the switch controls LLM lines.

Also corrected reply retries (FR-24): one total timeout, recheck switch before retry,
and pass the validator rejection reason to the correction call.

## Verification

244 Python tests and 11 browser tests pass, with all seven local synthetic release
checks green. New coverage includes actual AppSession confirmation, split answers,
context reset/safety, database reopen policy, off/on/off changes, nightly switching,
retry budgets/reasons, elapsed cap/no-limit/extension, closing cancellation and
browser audioCancel. Tests use fake model/audio objects; no paid calls were made.

These results do not establish real GPU latency, acoustic recognition, the latest
spoken Stop accuracy or a complete deployed workbook acceptance pass. Full FR-14
nonmatching-transcript presentation and persistent settings APIs remain separate.

## GPU installation

Stop the old server with Ctrl+C. Extract gpu-backend-four-fixes.zip and merge its
src/, web/, tests/ and docs/ folders into:

/home/mage1/patient-listener-voice/project

Replace matching files. Keep /home/mage1/patient-listener-voice/.venv, GPU constraints,
model caches, local environment and databases. This bundle carries the current
Python source, browser voice client/worklet/app and tests, so it also contains recent
voice safety, target-word and spoken Stop changes. No dependency reinstall or model
redownload is needed for these four fixes. No secrets/database/model weights included.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python run_tests.py
export VOICE_ENABLED=true
export AI_ENABLED=false
# If a persistent DB is selected, explicitly switch THAT DB off too.
if [ -n "${PL_DB_PATH:-}" ] && [ "$PL_DB_PATH" != ":memory:" ]; then
  python -m patient_listener.tools.switch --db "$PL_DB_PATH" --ai-enabled false --reason "GPU regression test"
fi
python -m patient_listener.app
```

The default PL_DB_PATH is :memory:. It is freshly initialized with AI off above.
For an existing file database, AI_ENABLED=false alone intentionally does not replace
a saved flag. Keep the CLI DB path identical to the server's PL_DB_PATH. Do not turn
AI on for these regression checks. Running token_factory_check is a paid diagnostic
and is not needed here.

Open http://127.0.0.1:8000/?voice=1 on the GPU machine and hard refresh.

## Browser checks

- Confirm greeting, captions, correct target and hints still work; a different plan
  word must not complete the current prompted exercise.
- Say stop during spoken output and check cancellation; check Stop button too.
- Getting words out: speak a sentence in multiple segments, with pauses. No sounds
  during a block. With AI off it keeps waiting until Done instead of purchasing a
  completeness call; the full-context data flow is established by automated tests.
- With the normal configured cap, expiry should cancel pending practice, play the
  closing line once and then end. Automated tests advance a synthetic clock; browser
  verification still requires real elapsed time or a deliberately configured test cap.
- Being clear is not among the three stock demo personas. Its regression test creates
  an isolated in-memory profile. Do not expect the current browser setup cards to
  persist that profile before the separate saved-settings API is implemented.

## Backend session control for extension

The authenticated WebSocket accepts {"type":"extend_session","minutes":30} to
lengthen the current session, or minutes:null for no limit. Shortening a cap, adding
a cap after no-limit, invalid types and values outside PauseConfig ranges are rejected.
Extension is measured from original Start, not from the time the control is sent.
This is a backend contract; P7 frontend wiring and durable per-person settings are
still open. No PIN is required to lengthen/remove a cap, as required by FR-61.

## Remaining work

These four fixes do not complete loudness calibration, saved console/patient settings,
FSRS/modes, real nightly clip rendering, carer tools, deployment/telemetry or PostgreSQL.
mm pronunciation and PostgreSQL remain deferred per the user's decision. See the
current progress audit for the full requirement matrix.
