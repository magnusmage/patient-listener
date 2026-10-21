# First browser voice integration (development only)

21 October 2026. GPU environment: Ubuntu 24.04, Python 3.12, PyTorch 2.9.1+cu128,
NeMo 3.0.0. Independent ASR/TTS and combined inference passed on the user's RTX 5070.
This new browser integration has NOT yet been verified on that GPU.

## Install this update

Stop the old API server with Ctrl+C. Merge the zip's src/, web/, tests/ and docs/ into
/home/mage1/patient-listener-voice/project, replacing matching files and keeping its sibling
.venv intact. This archive contains code and tests only, no API keys or local databases.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m pip install -c ../gpu-constraints.txt "silero-vad~=6.2"
python -m pip check
export VOICE_ENABLED=true
export AI_ENABLED=false
python -m patient_listener.app
```

AI_ENABLED=false avoids Token Factory credit usage in this voice test; the ASR and TTS remain
local on the GPU. Use one worker, no reload, and no other model-test processes on the GPU.
Silero's Python package includes its VAD weights; runtime imports no longer probe a nonexistent
nemo_toolkit module for the new connection path.

Open a browser ON THE GPU MACHINE at:

http://127.0.0.1:8000/?voice=1

Hard refresh to discard old client.js/app.js/worklet.js, choose Finding the word, and press
Start/Yes start. Allow the microphone. Expect spoken greeting and prompt, then speak the shown
practice word. Observe the caption and response. Test Help, yes/no confirmations, typed input,
and Stop. Browser playback uses local AudioContext at 22.05 kHz; microphone frames are 16 kHz
PCM16 in 160 ms packets. Headphones are recommended for the first acoustic test.

Use the GPU machine's localhost browser for this first test. Plain HTTP on its LAN IP is not
a browser microphone secure context; Windows access needs HTTPS/WSS or a localhost tunnel.
Do not expose this development API publicly as production authentication/enrollment.

If start fails, save terminal output and browser console errors. Do not repeatedly reinstall
all voice dependencies. The installation may reveal NeMo 3.0 API/config incompatibilities:
these must be fixed against actual GPU evidence, not inferred from mocked tests.

## Implemented in this update

- Reuses the two process-lifetime models; caches and VAD state are session-local.
- Cache-aware conformer_stream_step with [70,1] attention context, approved-word boosting,
  Silero speech events and partial/final transcript callbacks.
- A 640 ms silence closes an ASR segment only; the existing controller still owns turn endings.
- Detects safety phrases in partial transcripts before the final ASR segment.
- One voice connection per worker until capacity is measured; text sessions remain supported.
- Serialized GPU calls, bounded queues, sanitized error classes and no audio/transcript files.
- Sentence-level Magpie synthesis, PCM playback, playback acknowledgements, microphone muting,
  pending-audio cancellation on Stop/safety and resource cleanup after worker completion.
- Voice-mode selection via ?voice=1 and existing authenticated device-bound session tokens.

## Explicit remaining acceptance work

This is a development integration, not a completed workbook voice acceptance gate.
The /healthz endpoint remains 503 in voice mode and reports streaming_ready=false until real
GPU warmup/streaming acceptance is implemented. development_voice_enabled=true advertises the
experimental path without claiming production readiness.

Actual NeMo streaming accuracy, feature-chunk boundary artifacts, name/phrase boosting,
nine-second pauses, full current-turn transcript handling and memory/latency need measurements.
Synthesizing a full sentence before transmission does not establish first-audio latency targets.
The generic/hint clip cache, WSOLA/gaps/normalization, real loudness calibration, session caps,
Parakeet EOU advisory and Pipecat integration remain open. Spoken Stop cannot be recognized
while microphone input is muted during output; the Stop button cancels browser playback.
This is a known FR-04 acceptance gap, not a claim of complete spoken-stop compliance.

No model API credits were used in local verification. Tests: 203 backend tests passed with
local release gates green; 9 browser safety/auth/playback tests passed. Real GPU/browser
voice success is still pending the user's first test.

## References checked

- NVIDIA ASR model card: https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
- NVIDIA Magpie model card: https://huggingface.co/nvidia/magpie_tts_multilingual_357m
- NVIDIA cache-aware streaming example: https://github.com/NVIDIA/NeMo/blob/main/examples/asr/asr_cache_aware_streaming/speech_to_text_cache_aware_streaming_infer.py
- NVIDIA word boosting: https://docs.nvidia.com/nemo-framework/user-guide/26.02/nemotoolkit/asr/asr_customization/word_boosting.html
- Silero VAD: https://github.com/snakers4/silero-vad
