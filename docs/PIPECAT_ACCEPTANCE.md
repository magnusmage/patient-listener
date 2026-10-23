# Pipecat live voice integration: workbook D-07

## Implementation

The active authenticated WebSocket voice path now constructs a real Pipecat 1.12.0 Pipeline,
PipelineWorker and WorkerRunner per connection. These objects use in-process worker/bus
coordination only: there is no remote agent, network bus, dev runner or added public endpoint.

The actual processor chain is NeMoInput (existing Silero VAD and cache-aware NeMo ASR),
Patience (existing application/controller), MagpieOutput, BrowserOutput. Microphone PCM,
VAD started/stopped events, interim/final transcripts and TTS PCM travel as Pipecat frames.
All active recognition and synthesis go through this chain. Existing local model adapters
are retained; this does not switch speech to a remote NVIDIA NIM/Riva service.

Authentication and JSON control routing stay at the existing FastAPI boundary. Binary messages
are audio; JSON messages are controls. Each session retains bounded input/output queues.
Pipecat direct-mode processors await each downstream stage within those workers, preserving
ordering and backpressure without adding another audio queue. An independent input worker
continues to accept control-only speech during playback; typed Stop stays on the socket reader.

No default user-turn aggregator, Smart Turn, automatic turn ending, automatic VAD interruption,
RTVI observer, transcript/turn tracing, or framework idle timeout is enabled. Our patience
controller remains the only decision-maker. Existing target matching, check taps, hint
permission, safety and five-phrase calibration rules are unchanged.

Input is mono PCM16 at 16000 Hz; output is mono PCM16 at 22050 Hz. No Pipecat resampler or
MediaSender is used; custom socket output preserves cached bytes. This avoids the MediaSender
clipping and resampling paths called out in the workbook. Actual browser playback_done IDs
remain authoritative, not framework estimates of finished playback. No frontend update is needed.

Cached hints and fixed prompts reuse their existing audio and do not invoke Magpie again.
Live synthesis gets a five-second stall watchdog: the client gets speech_output_stalled and
the connection closes. Any late output is discarded. The GPU session remains occupied until
an in-flight kernel finishes; a Python cancellation cannot stop a running GPU kernel. A new
voice session constructs a fresh pipeline once the GPU slot is released. A permanently hung
GPU worker still requires an operational process restart; this code does not force-kill it.

Speech frame string/repr output is redacted. Stage failures log only stage name and exception
class, and return fixed client error codes. No transcript or PCM is persisted by this pipeline.
Voice runtime preflights the exact Pipecat version before loading models. Health reports
pipeline_framework and pipecat_version separately from unmeasured production readiness.
The old unused build_pipeline NotImplementedError factory was removed; app.audio retains
only shared events and its isolated transport-neutral adapter test harness.

## Dependency compatibility

Pipecat 1.12.0 requires soundfile~=0.13.1 and soxr~=1.0.0. Previous voice-extra bounds
(soundfile~=0.14 and soxr~=1.1) had no overlap with these. The project now follows Pipecat's
actual bounds and explicitly records this deviation from the workbook's library table.
The models, audio sample rates and hint processing behavior are unchanged.

The pipeline extra installs the CPU framework without requesting the voice extra's NeMo,
PyTorch or NVIDIA-service dependencies. Existing GPU model libraries are reused.

## GPU update and test

1. Stop the server. Copy the update ZIP files into the existing project, preserving paths.
   Keep the database, .env, model weights and existing virtual environment.
2. From the project folder:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m pip install -e '.[pipeline]'
python -m pip check
```

3. Keep paid inference off for this integration test. For the current SQLite setup:

```bash
python -m patient_listener.tools.switch --db "$PWD/pl.db" --ai-enabled false --reason "Pipecat smoke test"
python -m patient_listener.app
```

   The server must use the same persistent database. Setting AI_ENABLED in the shell does
   not override the saved database switch. No API key is needed to test Pipecat itself.
4. Open a new browser voice session. The server should log:

```text
Voice pipeline started framework=pipecat version=1.12.0 input_hz=16000 output_hz=22050
```

5. Verify greeting/prompt audio, transcript display and the displayed target's success.
   Saying a different list word must not complete the target. Check uncertain confirmation
   and Being clear's check tap. Ask for cached hints and verify spoken playback.
6. Pause for at least 15 seconds without answering or requesting a hint. Existing profile
   patience rules should apply; framework silence must not end the turn automatically.
7. Test spoken Stop and the Stop button during playback. Confirm no late audio/transcript
   appears. Test the synthetic safety phrase and verify practice stays stopped.
8. Reconnect and start a fresh session: the patient/GPU slot should be available again.
   Briefly test Being heard calibration and microphone-setting reset too.

Health remains HTTP 503 / streaming_ready=false in voice development mode until the separate
production streaming/latency/concurrency gates are measured. That flag does not mean the
Pipecat dependency is absent; check pipeline_framework, version and the session-start log.

## Verification and limits

CPU tests use real Pipecat and synthetic model adapters: lifecycle, standard frame dispatch,
fixed rates, byte-identical cached audio, terminal safety, stale capture invalidation, mixed
JSON/binary authenticated WebSocket traffic, failure handling and stalled-kernel cleanup.
Text-only startup was checked separately and imported neither Pipecat nor PyTorch.
No paid model calls, NeMo/Magpie weight downloads or GPU inference were performed for these tests.
Actual NeMo/Magpie behavior on the user's GPU still needs the smoke test above. These checks
do not prove the workbook's deployed latency, Stop timing, concurrency or clinical gates.

## Primary references

- Workbook D-07, stack turn-handling rules and Pipecat issues 13-22.
- Installed pipecat-ai 1.12.0 source and package metadata (pinned in pyproject.toml).
- https://github.com/pipecat-ai/pipecat/tree/v1.12.0/src/pipecat
- https://docs.pipecat.ai/server/fundamentals/custom-frame-processor

Validation result: 410 backend tests passed; nine opt-in PostgreSQL tests skipped in this run.
All 24 browser checks passed; pip check reported no broken requirements. Ten added tests
exercise the actual installed Pipecat framework with synthetic inference adapters.
