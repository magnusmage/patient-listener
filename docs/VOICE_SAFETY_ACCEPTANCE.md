# Voice safety and turn-taking update

21 October 2026. Follows the first working browser voice integration.

## Changes

- Preserve a pending hint offer while speech recognition processes spoken yes/no.
- Resume normal word matching when the user speaks an ordinary answer instead.
- Wait for browser playback completion before advancing to the next prompt.
- On safety/end, close the voice socket and cancel queued audio. The browser also
  cancels playback and microphone capture directly when either event arrives.
- Verify that disconnects and failed startup release the patient and GPU slots.

## Local verification

210 Python tests and 10 browser tests passed. The added regression cases cover
spoken hint confirmation, a new pause after resumed speech, unfinished repeated
speech in Getting Words Out, partial-transcript safety, playback-gated advancement,
safety cancellation, disconnect/reconnect and startup failure cleanup.

These are local automated checks with fake audio/model components. They do not
establish real GPU latency, audible Stop timing or workbook submission acceptance.
No paid model calls were made.

## Install on the GPU machine

Stop the running server. Extract gpu-voice-safety-update.zip and merge its src/,
web/, tests/ and docs/ folders into:

/home/mage1/patient-listener-voice/project

Replace matching files; preserve the sibling .venv, existing configuration and
local database. This incremental update assumes the previous browser voice update
is already installed. There are no dependency changes.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
export VOICE_ENABLED=true
export AI_ENABLED=false
python -m patient_listener.app
```

AI_ENABLED=false avoids Token Factory credit usage during these checks. Open
http://127.0.0.1:8000/?voice=1 on the GPU machine and hard refresh before starting.

## Real browser checks still required

1. Finding the word: wait for the hint offer, then say yes. A hint should follow.
   Repeat with no, then with an ordinary word answer; the session must keep working.
2. Pause, resume speaking, then pause again. The controller's pause timing should
   restart from the new speech; an old timer must not interrupt immediately.
3. Getting Words Out: say an unfinished phrase such as 'my my my', then pause for
   about 12 seconds. It should keep waiting rather than treat the phrase as complete.
4. Complete an item. The next prompt must wait until the preceding audio finishes.
5. Press Stop while the app speaks. Audio and microphone capture should stop;
   queued speech must not play later. Start again and confirm normal operation.
6. While listening, use a synthetic safety test phrase such as 'my arm is weak'.
   Confirm the safety card appears and practice ends. Restart for subsequent tests.
7. Close the session tab, reopen it, and start again. Repeat after stopping a
   session. The prior connection must not permanently hold the GPU/session slot.

Record observed results and timings before marking real voice acceptance complete.
The existing mm pronunciation problem is deferred. Spoken Stop during playback
remains a gap because microphone capture is muted during output; this update tests
the Stop button. Cached clips, audio calibration, measured latency, EOU/Pipecat
requirements and the remaining workbook gates still need work. PostgreSQL is
deferred to the end by project decision; that does not remove a workbook requirement.

## Prompted-word matching correction

A GPU browser test revealed that saying Leo or kettle while Biscuit was prompted
logged the other plan word and advanced the cursor. The browser AppSession now
opts into target-only matching for its individual prompts. The default core
controller still supports workbook-style matching across the approved plan for
open conversation. This scope choice distinguishes a specific exercise from a
broader conversation; it does not change FR-22 scoring or confirmation thresholds.
Only approved entries are eligible. Spoken and typed answers share the same rule.

Verification: 214 backend tests passed without paid calls. Regression tests cover
other approved words, the correct target, a typed wrong word followed by yes,
a close target match requiring confirmation, open-plan matching, and an ineligible
target. Real GPU verification of this correction remains pending.

For gpu-target-word-fix.zip, merge the extracted src/, tests/ and docs/ folders
into the same GPU project directory, restart the server as above, and start a new
browser session. With Biscuit prompted, say Leo and kettle separately: neither
should produce a tick or move to another prompt. Then say Biscuit: it should work.
No dependency changes or model downloads are required.
