# Patient Listener — platform and model feedback

Updated **28 October 2026**. Feedback from building a patient-paced voice practice app with Nebius Token Factory, NVIDIA NeMo/Nemotron/Magpie and Pipecat.

This document records project experience. It distinguishes observed behavior, our integration mistakes and requested improvements. It does not assert an upstream defect without a reproducible isolated case. No new paid requests were made to prepare it.

## What we used

| Component | Use in Patient Listener |
| --- | --- |
| Nebius Token Factory | OpenAI-compatible runtime text inference |
| `nvidia/Nemotron-3_5-Lightning` | Short replies and completeness decisions within controller budgets |
| `nvidia/nemotron-3-super-120b-a12b` | Optional meaning-hint generation from a supplied word/cue record |
| `nvidia/nemotron-speech-streaming-en-0.6b` | Local GPU speech recognition through NeMo |
| `nvidia/magpie_tts_multilingual_357m` | Local speech generation and cached prompts/hints |
| Pipecat 1.12.0 | Frames/processors around our own session and timing controller |

Final hosting is a self-hosted CPU API/PostgreSQL/Nginx server plus a separate GPU. We do not claim a deployed Nebius AI Cloud voice endpoint, evaluated Hermes/OpenShell runtime or a Tavily integration. Feedback below covers tools we actually exercised.

## What worked well

- The OpenAI-compatible Token Factory interface let us keep provider calls behind a small adapter instead of changing the controller or frontend.
- Separate Lightning and Super roles fit our two workloads: constrained conversational wording and preparation-time hint authoring.
- JSON-object responses could be parsed and passed through our own validators. Invalid or late results could fall back to templates without ending practice.
- NeMo ASR and Magpie ran together on the development RTX 5070 with 12 GB VRAM. A user-reported combined model test showed about 5.86 GiB peak PyTorch tensor allocation; this is configuration-specific, not a minimum hardware claim.
- Prepared hint clips and fixed prompts reduced repeated synthesis work and separated voice playback reliability from live text-model timing.

## 1. Token Factory response time versus an interactive deadline

**Observation.** Independent text diagnostics sometimes accepted a model reply after the app's live-response budget had already elapsed. A reported single-run check produced:

| Path | Elapsed | Result |
| --- | --- | --- |
| Lightning diagnostic | 2.977 s | Accepted |
| Super diagnostic | 1.189 s | Accepted |
| Validated reply pipeline | 1.048 s | Model reply |

These are user-supplied terminal results from different calls, with synthetic inputs. They are not a benchmark, a latency distribution, time-to-first-token or microphone-to-first-audio measurements. Earlier and later calls varied; some browser sessions used timeout fallbacks.

**Impact.** A successful standalone call did not guarantee a model-authored reply within the live controller's 1.5-second budget.

**Our response.** Keep the application deadline, bound validation retry within the reply path, return templates when needed, cap calls and log model/outcome/elapsed time without request text. We temporarily tried a longer deadline during development; that experiment is not evidence that the original latency gate passed.

**Requested improvement.** Publish per-model interactive guidance: cold/warm behavior, complete-response versus first-token latency, recommended output sizes and how request cancellation affects usage. These would help builders select a realistic voice workload before spending a larger evaluation budget.

Evidence: [adapter](src/patient_listener/llm/token_factory.py), [reply deadline policy](src/patient_listener/llm/reply.py), [small diagnostic](src/patient_listener/tools/token_factory_check.py).

## 2. Structured output and thinking controls

**Observation.** Small diagnostic runs accepted Lightning/Super JSON-object output using json_object mode and enable_thinking=false. The diagnostic correctly left its full G-03 raw-JSON evidence flag false because the required sample set was not completed.

**Our response.** Parse JSON explicitly, check the expected field, strip think-tag content defensively, validate wording and fall back on malformed/empty/rejected output. The production adapter currently requests json_object; we do not claim that strict JSON Schema/Instructor integration has been established.

**Requested improvement.** Keep a model-specific capability matrix for JSON object/schema support, thinking controls, reasoning/output accounting, response finish reasons and cancellation behavior. Provide minimal examples for the actual model identifiers exposed by /models.

No isolated provider response-schema defect was established by these small checks.

Evidence: [Token Factory request construction](src/patient_listener/llm/token_factory.py), [raw-response flags](src/patient_listener/tools/token_factory_check.py), [validators](src/patient_listener/llm/validate.py).

## 3. Grounded, restrained conversational wording

**Observation.** In one reported browser test, a model-authored reply introduced an unrelated fox comparison after a question about Biscuit. The user confirmed that the transcript and Magpie audio matched the reply, making wording/grounding the relevant investigation rather than pronunciation alone. No sanitized committed raw provider transcript is attached, so this remains a reported qualitative example.

**Our response.** Strengthen prompts around supplied facts, treating transcripts as untrusted practice content, avoiding appearance/personality comparisons and preferring a neutral acknowledgement when uncertain. Validate output in code. Models do not receive camera input or decide a patient's condition.

**Requested improvement.** Provide examples for restrained acknowledgements and short grounded speech, including uncertainty/fallback behavior. Fluent output needs semantic evaluation; syntactically valid JSON is insufficient.

Evidence: [reply prompt](src/patient_listener/llm/token_factory.py), [reply validation](src/patient_listener/llm/validate.py). We do not claim the guards guarantee semantic correctness.

## 4. Setup visibility, credentials and SDK compatibility

**Observation.** Development included malformed-request errors and a local PowerShell invalid-control-character error during key setup. A later check found a configured key but no OpenAI SDK installed in the GPU virtual environment; the app consequently used TemplateLlm. These observations do not establish a Token Factory service outage.

**Our response.** Check configuration/SDK availability without printing keys, validate whitespace/control characters for diagnostics, and separate provider failures from local adapter selection. The dependency resolver also encountered incompatible requested OpenAI/Instructor jiter bounds; our resolved versions are documented rather than forced with --no-deps.

**Requested improvement.** Offer a low-cost preflight that separates authentication, SDK/version, model availability and response-format problems. A deployment should make the selected model/template adapter visible without exposing credentials. Tested SDK combinations and errors that name the failed layer would shorten onboarding.

Evidence: [adapter selection](src/patient_listener/llm/factory.py), [compatibility notes](docs/DEPENDENCIES.md), [locked Windows LLM dependencies](requirements-llm-windows-py312.lock).

## 5. NeMo packaging and GPU warmup

**Observation.** Imports and model loading succeeded, but an early Docker inference path failed after microphone input. Runtime compilation required compiler tools and an executable writable cache location. The host also initially reported an NVIDIA driver/library mismatch before its working GPU check. These were local environment/packaging issues, not established model defects.

**Our response.** Preserve the tested CUDA/PyTorch/NeMo stack, include build tools in the runtime fix, use writable executable cache paths, and exercise VAD, ASR/boosting and fixed TTS clips before marking voice ready. Updating Python application code should reuse the tested image rather than reinstall the whole GPU stack.

**Requested improvement.** Document first-inference/JIT requirements alongside import requirements, give tested RTX/Blackwell combinations and distinguish executable cache requirements from ordinary model cache mounts. A small real-inference health probe would have caught this earlier than imports alone.

Evidence: [runtime image fix](deploy/Dockerfile.voice-runtime-fix), [voice launcher](scripts/run_local_voice_container.sh), [warmup tests](tests/test_voice_warmup.py), [container notes](docs/GPU_CONTAINER.md).

## 6. Magpie short utterances and prepared speech

**Observation.** A bare mm backchannel sounded unintelligible in an early reported voice test. Short isolated utterances need listening review even when normal sentences synthesize successfully.

**Our response.** Prepare fixed prompts once, use a more explicit Mm-hmm. input for the default backchannel, support a reviewed synthetic clip, and cache model/text/voice/processing-specific hint audio. Implement WSOLA pacing, inter-sentence gaps and loudness normalization for prepared hints.

**Requested improvement.** Include recommended inputs for brief acknowledgements, explicit speaker/voice mapping and short-utterance examples in model documentation. Developer-facing guidance on speed and normalization would help keep speech consistent.

We have not recorded the workbook's three-listener blind preference test, and do not claim naturalness or clinical suitability from a successful WAV/transcription round trip.

Evidence: [prepared-audio notes](docs/PREPARED_AUDIO_ACCEPTANCE.md), [prepared-audio tests](tests/test_prepared_audio.py), [audio processing](src/patient_listener/voice/processing.py).

## 7. Platform boundaries and small credit budgets

**Observation.** The team had working Token Factory inference access while compute/database deployment needed a separate hosting plan. We eventually selected self-hosted CPU/GPU infrastructure and retained Nebius for runtime LLM inference.

**Our response.** Keep cloud inference and local speech separate in documentation, use synthetic diagnostic inputs, allow explicit small run counts, make AI optional through a persisted switch, and generate templates/prepared audio without paid text calls when desired.

**Requested improvement.** Make the boundary between inference access, compute provisioning, billing prerequisites and credit applicability explicit during onboarding. Provide a published minimal-credit validation path and cost/cancellation visibility. We do not report a measured end-to-end operating cost or assert a credit-transfer policy here.

## Reproducing a small model diagnostic

Only after configuring a private key and consenting to paid calls:

```bash
PL_ENV_FILE=/absolute/path/to/private.env \
python -m patient_listener.tools.token_factory_check \
  --runs 1 --pipeline-runs 1 --output token-factory-smoke.json
```

This sends two independent diagnostic calls plus a pipeline attempt that may retry once. It measures complete text requests and validation, not live first-audio latency. A timeout can still consume provider usage. Do not publish keys, request transcripts, person facts or an unsanitized report.

For zero paid requests, use template mode and mocked tests instead:

```bash
PL_ENV_FILE=/absolute/path/to/private.env \
python -m patient_listener.tools.switch --ai-enabled false --reason "Template-only test"
```

The server key/SDK configuration must still be checked separately before claiming live model use. GPU speech can remain enabled while Token Factory calls are off.

## Highest-value improvements

1. Model-specific structured-output and thinking-control examples.
2. Interactive latency/cancellation guidance and low-credit diagnostics.
3. Clear adapter-selection and SDK compatibility checks.
4. NeMo first-inference/container-cache requirements.
5. Magpie voice mapping and short-utterance guidance.

This file is ready to adapt into the Devpost feedback section. Its presence in Git is not evidence that the submission form has been completed. Clinical effectiveness, universal speech recognition accuracy, strict latency compliance and unused platform integrations are not claimed.
