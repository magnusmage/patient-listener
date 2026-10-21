# GPU model startup checkpoint

21 October 2026. This is model lifetime integration, not completed microphone streaming.
The remote Ubuntu machine already passed independent and combined NeMo/Magpie inference;
reported peak tensor allocation was 5.86 GiB on an RTX 5070 12 GB.

Copy this update into /home/mage1/patient-listener-voice/project, preserving the sibling .venv.
Then run from that project directory:

```bash
source ../.venv/bin/activate
export VOICE_ENABLED=true
python -m patient_listener.app
```

Use one server worker and do not enable reload; every worker loads its own model copies.
The first load can use the model download cache created by the earlier tests.
With no VOICE_ENABLED flag, Windows/local text mode remains unchanged.

From a second terminal:

```bash
curl -s http://127.0.0.1:8000/healthz
nvidia-smi
```

Expected JSON: status=voice_not_connected, voice_enabled=true, models_loaded=true,
streaming_ready=false. HTTP 503 is intentional: model loading alone does not pass the
workbook's warm streaming-readiness acceptance criterion. This endpoint must not be used
as a green production readiness check until streaming and warmup are implemented.

Both models remain referenced by app.state.voice_runtime throughout server lifetime.
Startup fails when CUDA/model loading fails rather than silently claiming voice readiness.
Ctrl+C triggers cleanup. Readiness metadata contains no credentials, input audio or transcripts.

Remaining: per-session streaming ASR caches and phrase boosts, Silero VAD, EOU advisory,
real output action/TTS queue, browser playback/half-duplex, bounded buffering and cancellation,
model warmup, precision/latency/load checks. Keep VOICE_ENABLED off in the deployed demo until
these are complete. No real API calls or GPU model downloads were made by the Windows tests.
