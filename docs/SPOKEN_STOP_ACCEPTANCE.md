# Spoken Stop during playback

21 October 2026. Incremental update after d06d981.

## Workbook behavior

FR-04 and stack latency lever 7 require ASR to remain active during playback while
only the exact word stop acts. Normal practice remains half-duplex at the controller
boundary. FR-05 requires audio stop within 200 ms and session end within one second;
real timing acceptance is still pending.

## Implementation

- The browser no longer mutes its worklet on audioStart. Existing browser echo
  cancellation remains enabled; the stream stays within the existing voice endpoint.
- Playback frames reach ASR, but only a partial or final transcript equal to stop
  (case-insensitive, with terminal .!? allowed) dispatches a Stop control.
- Speech events, captions, answers, other commands and silence from playback audio
  never enter the practice controller. Stop now is intentionally not an exact match.
- Input epochs discard queued/in-flight transcripts across playback boundaries.
  Recognition/VAD/buffer state resets under the GPU lock before the next epoch's input.
- Existing terminal events cancel playback/capture and discard pending output.

## Verification

216 backend tests and 10 browser tests passed without paid calls. Added tests cover
exact partial Stop during output, ignored non-Stop playback events, and in-flight
transcripts discarded across a playback boundary. GPU acoustics are not mocked-test
results and have not been accepted.

## Apply and test on GPU

Stop the old server. Merge src/, web/, tests/ and docs/ from gpu-spoken-stop-update.zip
into /home/mage1/patient-listener-voice/project, replacing matching files. Keep the
sibling .venv and local configuration/database. No dependencies or downloads change.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
export VOICE_ENABLED=true
export AI_ENABLED=false
python -m patient_listener.app
```

Open http://127.0.0.1:8000/?voice=1 on that machine, hard refresh and start a new session.

1. Start with headphones. Say stop while a greeting or reply is audibly playing.
   Audio must cancel, the session must end, and queued audio must not resume.
2. Start another session. Say a practice word or help during playback. It must not
   log an attempt or trigger a practice response. Answer normally once playback ends.
3. Try Stop during a hint and between sentences. Check the Stop button still works.
4. Repeat with speakers to check for self-triggering or echo; record browser/device.
5. Reconnect and confirm the next prompt still accepts its own target word.

Record failures and timings. Browser echo cancellation does not guarantee acoustic
isolation. GPU ASR and TTS still serialize on one lock: recognition can be delayed
while a synthesis call is running. This implementation does not prove the 200 ms /
one-second limits, and may need additional work after real GPU measurement.
The prior microphone-muting description in GPU_BROWSER_VOICE.md describes the old
integration; this document supersedes it for this update. mm and PostgreSQL remain
deferred. No transcript or audio persistence is added.
