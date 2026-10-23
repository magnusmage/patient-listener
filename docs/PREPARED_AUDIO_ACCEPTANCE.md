# Prepared audio update — 23 October 2026

## Behaviour and workbook scope

Fixed Magpie lines are synthesized once at GPU startup and held in memory. This
includes the listening sound, hint offer, rest offer, A bit stronger? and the
closing line. Replaying them does not call Magpie or Token Factory. Startup logs
Prepared fixed audio clips count=10 after a complete preparation, and fails if
preparation cannot finish; it does not publish a partial cache.

The mm caption uses the Magpie input Mm-hmm. instead of bare mm. This removes
live synthesis of bare mm during a pause. Its actual pronunciation has not been
auditioned on the developer GPU in this change. Listen before accepting it. If it
is unsuitable, BACKCHANNEL_CLIP_PATH can select a reviewed synthetic Magpie WAV:
mono, PCM16, 22050 Hz, 0.1 to 3 seconds. Never use a patient's recording. This
option validates and normalizes that fixed asset; it does not collect user audio.

Hint generation synthesizes each sentence, slows it with audiotsm WSOLA at 0.8x,
inserts 500 ms silence between sentences and normalizes the prepared clip toward
-20 LUFS with pyloudnorm. Pitch is preserved by time stretching, not sample-rate
relabeling. Generic and live synthesized lines are normalized too. Gain is capped
for peak headroom, so extreme clips can remain quieter than the configured target
rather than clip. Clips shorter than 400 ms repeat for loudness measurement only;
the stored/playable duration is unchanged. Very short measurements are approximate.

The processed hint cache is checked against model, voice, exact text and processing
profile (version, speed, gap and loudness). Old clips remain stored as legacy, but
are not played as processed clips. A missing or stale hint remains visible as text
with You can read the hint.; it never triggers live hint TTS. Generate current
clips before the demo to satisfy the audio requirement and measure latency.

G-06 still requires three listeners to compare naturalness. HINT_AUDIO_RATE=1.0
implements the workbook's normal-speed fallback with the same gaps if that gate
fails; record the listening result before selecting it for the final demo. No
human listening gate, actual Magpie pronunciation, GPU latency or overall voice
readiness is claimed by the CPU tests.

## GPU installation

Stop the server. Copy the ZIP contents into ~/patient-listener-voice/project,
preserving .env, pl.db and the sibling .venv. The ZIP contains no credentials,
database or model weights. Install only these small audio dependencies if missing;
do not reinstall PyTorch/NeMo or the whole voice extra:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m pip install 'pyloudnorm==0.2.0' 'audiotsm==0.1.2'
python -m pip install -e . --no-deps
```

Existing SQLite files receive the additive profile column at startup. Existing
cached clips and all practice data are preserved. Take a backup before updating.
If using PostgreSQL, apply the new Alembic migration before starting the server:

```bash
python -m patient_listener.tools.database upgrade
```

This advances PostgreSQL revision 0001 to 0002 without deleting old clips. Keep
PL_DB_PATH unset when using PostgreSQL. No PostgreSQL command is needed for the
current SQLite GPU demo.

For that SQLite demo, keep paid calls off and start voice:

```bash
python -m patient_listener.tools.switch --db pl.db --ai-enabled false --reason audio-test
export PL_DB_PATH="$PWD/pl.db"
export VOICE_ENABLED=true
export NIGHTLY_ENABLED=false
export HINT_AUDIO_RATE=0.8
python -m patient_listener.app
```

Startup now spends local GPU time preparing ten fixed clips. Wait for preparation
and Application startup complete before opening a session. It makes no Token
Factory calls. Once running, use another terminal with the same project and venv
and no browser practice session active:

```bash
python -m patient_listener.tools.generate_plan --person margaret --max-words 4
```

Enter the current therapist console token at the hidden prompt. Omitting --use-ai
keeps Super calls at zero. This regenerates up to four approved words and all
three processed hints per word (up to twelve clips). The available words and
scheduler decide the exact plan; it is not a promise of a fixed count. For
PostgreSQL, use the configured DATABASE_URL and omit SQLite --db provisioning
arguments when issuing a new console token.

## Browser acceptance

Hard-refresh both new JavaScript and source-backed server sessions. In the real
?voice=1 mode:

1. Margaret: pause until the listening sound. Confirm it is a short natural mm,
   not letters or unrelated words. Repeated pauses must use the same clip.
2. Request hints one level at a time. Confirm audio starts from cached clips, is
   slower without a lower pitch, and the level-three sentences have a clear gap.
3. A deliberately stale/unprepared hint must remain readable and must not start
   live synthesis. Regeneration restores audio for its current profile.
4. Test Stop during cached playback and its sentence gap. No queued audio should
   follow Stop. Recheck spoken Stop and normal target-word matching.
5. Daniyal: pauses must remain quiet; warming the cache must not cause extra
   listening sounds or enable hints for this profile.
6. Joseph: five-phrase setup and measured feedback must still work. Cached
   A bit stronger? must not create an ASR answer from playback.
7. Record three-listener G-06 comparison and measured hint-start latency separately.

Automated tests use synthetic CPU signals and fake model renderers. They verify
WSOLA duration/pitch, gap samples, LUFS, short clips, cache identity, legacy SQLite
upgrade, cached playback/Stop and missing-cache behavior. A disposable PostgreSQL
test also checks populated 0001->0002 upgrade and existing database integrations.
No patient's audio or transcript is written by this feature.

References: https://audiotsm.readthedocs.io/en/latest/tsm.html and
https://github.com/csteinmetz1/pyloudnorm
