# Being heard: measured session loudness (23 October 2026)

Requirement: workbook FR-13 and its Loudness against the person's own baseline
section. This change replaces the backend's alternating strong/weak stand-in.
It does not claim live browser/GPU acceptance or that the whole workbook is done.

## Implemented

* Capture 16 kHz PCM as before. Silero-positive 32 ms frames alone contribute to
  utterance RMS; non-speech does not lower the measured level. Energy/count totals
  are accumulated without retaining another copy of audio.
* Five everyday calibration phrases, one explicit Use this phrase tap per phrase.
  Pauses within a phrase cannot silently advance calibration. Multiple recognized
  segments are combined by their energy and duration before accepting that phrase.
* Baseline is the median of five phrase levels, kept only in this session. Read
  at a comfortable strong level, one hand's width from the microphone.
* After calibration, a level at least 2 dB below baseline produces A bit stronger?.
  The bar uses a bounded relative position. No dB value, baseline or microphone
  device ID is sent to the browser, written to the database or logged.
* The person can choose Practise without voice level to skip calibration and keep
  using speech or typing without a fabricated meter.
* Typed input cannot calibrate or fake loudness. Word matching remains a separate
  core decision. Combined Being clear still requires its check tap.
* Browser requests automatic gain and noise suppression off, plus echo cancellation
  off. Safari retains echo cancellation, as specified by the workbook. Actual
  getSettings() values are checked. Unavailable or conflicting settings produce an
  honest unavailable message instead of a made-up level; talking/typing still work.
* A changed device, sample rate or processing setting resets calibration and
  invalidates queued/in-flight input. Stop and safety discard later measurements.
  Hoarseness red flags also stop calibration/practice through the existing core.

The minimal browser changes are required to collect stable audio, show the setup
phrases and confirm them. The offline ?demo=1 replay is still simulated; test this
feature with the real ?voice=1 path, not the browser-only replay.

## GPU installation and test

Copy the update's source/web paths into ~/patient-listener-voice/project after
stopping the server. Preserve .env, pl.db and the sibling virtual environment.
No NeMo/PyTorch reinstall or extra packages are needed for this change.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m pip install -e . --no-deps
# For the CURRENT SQLite demo, stop paid model calls using the persisted switch:
python -m patient_listener.tools.switch --db pl.db --ai-enabled false --reason loudness-test
export PL_DB_PATH="$PWD/pl.db"
export VOICE_ENABLED=true
export NIGHTLY_ENABLED=false
python -m patient_listener.app
```

If this server already uses PostgreSQL, omit --db, unset PL_DB_PATH and keep the
configured PostgreSQL DATABASE_URL instead. AI off affects Token Factory calls;
the local ASR/TTS models still work. Nightly is disabled for a controlled test.

Open the existing secure browser URL with ?voice=1 and hard-refresh so both new
JavaScript files load. Start Joseph / Being heard. Keep Stop accessible and use a
quiet room and headphones for the first test.

1. Read each of the five displayed phrases at a comfortable strong level. Pause;
   Use this phrase becomes available after voiced audio is processed. Tap it once.
2. No loudness judgment is shown during setup. After the fifth tap, ordinary
   practice begins with the line representing the level you chose today.
3. Say a phrase at a similar level, then softly at the same distance. The bar
   should change and sufficiently softer speech should trigger A bit stronger?.
   Human volume changes are qualitative; the exact 2 dB boundary has fixture tests.
4. Type an answer: it must not create measured loudness feedback.
5. Restart the session: it must ask for five phrases again. Changing the microphone
   or its processing settings must also require a fresh baseline.
6. Check Stop during calibration/playback and the normal safety fixtures. Test
   Chrome/Edge first, then Safari separately for its documented echo exception.
7. Recheck Margaret's word practice and Daniyal's quiet waiting. For combined
   Being clear, word success must still require the person's check tap.

If the browser reports Voice level is unavailable, it did not confirm the required
processing settings. Do not treat that session as a passed calibrated voice test.
The browser reports its settings; this is not a server-verifiable hardware attestation.
Live microphone accuracy and OS-level gain behaviour still need hands-on verification.
No acoustic value is a health assessment, and none is used to infer health changes.
