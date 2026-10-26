# GPU container: local acceptance before Nebius

This packages the existing voice role only. API port8000 stays in the host virtual
environment; the container replaces GPU port8001. No cloud resources, registry
push, model credits or production-readiness claim are part of this step.
Workbook D-09 still targets Nebius Serverless L40S eu-north1. The Linux host-network
run below is a local acceptance arrangement, not the cloud network topology.

The candidate uses Python3.12, PyTorch2.9.1 CUDA12.8 wheels, NeMo3.0.0 and
Pipecat1.12.0, matching the known GPU-host stack. Official installation references:
- https://pytorch.org/get-started/previous-versions/
- https://docs.nvidia.com/nemo-framework/user-guide/25.11/installation.html

Torch wheels supply the CUDA userspace runtime; the host supplies its NVIDIA driver
and NVIDIA Container Toolkit. A GPU-enabled Docker runtime is required. The builder
installs NeMo ASR/TTS, native audio libraries and the existing pinned Flite/CMU
pronunciation assets. It imports ASR/Magpie without downloading model weights.
There is no model inference during the build. Dependency/network downloads do occur.

The constraints pin the main GPU packages, not every transitive dependency or the
base-image digest. The installed inventory is stored at /opt/voice-installed.txt.
After a successful target-machine build, capture that inventory and the image digest
for the release; a validated Linux lock and immutable base/image pins remain release
work. This image has not been built or run by the Windows development environment.

## Build on the GPU machine

Copy this update over the existing project, preserving .env.split, pl.db/WAL,
the virtualenv and all model caches. Keep the working services running during build:

```bash
cd ~/patient-listener-voice/project
docker build -f Dockerfile.voice -t patient-listener-voice:local .
```

The existing Docker allowlist excludes secrets, database records, reports and model
caches. No API keys or authentication files belong in build arguments or images.
The build may take time and disk space; it does not spend Token Factory credits.
If Docker reports no GPU driver/runtime, install/configure NVIDIA Container Toolkit
before the container test; do not change the already-working Python environment.

## Swap only the voice process

1. End the browser practice session. Stop only the host voice server with Ctrl+C.
   Leave the API process running. Ensure the saved AI switch is off:

```bash
source ../.venv/bin/activate
python -m patient_listener.tools.switch --db pl.db --ai-enabled false --reason gpu-container-check
bash scripts/run_local_voice_container.sh
```

2. Wait for Application startup complete. In another terminal:

```bash
curl --max-time 5 http://127.0.0.1:8001/healthz
```

Expect role voice, models_loaded true; voice_development/HTTP503 still reflects the
unpassed production-readiness measurements. Docker health checks /livez only.

3. Open the SAME enrolled browser at http://127.0.0.1:8000/?voice=1.
   Test transcript, spoken reply, hint playback and Stop. End that session, then:

```bash
python -m patient_listener.tools.generate_plan --person margaret --max-words 4
```

Use the console token, without --use-ai. Expect model_attempts zero and three
rendered clips per selected word. Start a fresh session and check prepared hints.

The script runs as your Linux UID/GID so the 0600 config and SQLite WAL remain
accessible without chmod777/root. It binds the existing project directory at the
same absolute path for shared SQLite, including WAL/SHM, with a read-only overlay
for .env.split. This trusted local container can write that directory: use only the
image built from this project. Production must replace this development bind with
shared PostgreSQL and injected secrets. The installed package lives in /opt/venv,
not the mounted project. Host networking keeps existing loopback URLs unchanged;
this launcher is Linux-only and intentionally binds voice to loopback.

Only the existing HuggingFace, torch and NeMo cache directories are mounted under
/cache, writable as the host owner. HuggingFace credentials, if present in its cache,
remain sensitive and must not be copied into the image. Missing cache assets may
download at first startup. The launcher respects exported HF_HOME, TORCH_HOME and
NEMO_CACHE_DIR host paths; default NeMo cache is ~/.cache/torch/NeMo/NeMo_3.0.0.
There is no forced offline mode until all required assets are verified in cache.

## Roll back / capture build evidence

Ctrl+C stops/removes the foreground container. Restore the previous host voice:

```bash
python -m patient_listener.tools.services run voice
```

No database copy, config regeneration or token rotation is needed.
After a passing test, capture the installed inventory and local image ID:

```bash
docker run --rm --entrypoint cat patient-listener-voice:local /opt/voice-installed.txt > voice-installed-linux.txt
docker image inspect --format '{{.Id}}' patient-listener-voice:local
```

The user verified the repaired GPU image on the local Linux machine. PostgreSQL0005/TLS, Serverless ingress,
private-render networking, model-cache persistence/cold start, G-02 Pakistan/UK
WebSockets and other workbook acceptance gates remain open. Do not deploy replicas
or claim readiness based on Docker /livez health alone.

Local verification: launcher Bash syntax passed and all 11 focused service-split
tests passed. The user also verified remote prepared-plan generation (4 items,
12 clips, zero model calls) and playback before this packaging change.

The launcher explicitly selects --runtime=nvidia alongside --gpus all, as required
when NVIDIA Container Toolkit uses CDI mode. This is a launch-only change; the image
does not need rebuilding. See https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/cmd/nvidia-container-runtime/README.md

Local arbitrary-UID startup fix: the launcher supplies USER/LOGNAME for Python's
getpass username lookup and a UID-owned tmpfs home at /run/listener. Matplotlib,
Fontconfig, Lhotse and compiler caches can write there. Model caches retain their
explicit persistent bind mounts. The scratch home is disposable and is not a new
patient-data or model store. This avoids requiring a host UID passwd entry, running
as root, or changing permissions on the database/config. No image rebuild is needed.

## Inference-time compiler repair

The first container reached model startup and TTS but failed in NeMoVAD_ASR on
microphone input with a sanitized RuntimeError. A target-host check confirmed cc,
gcc and g++ were absent. The runtime now includes build-essential because Triton
can compile host launchers during inference. Adding the compiler exposed the
subsequent shared-library mapping failure described below. The final repaired image
and launcher passed the user speech retest. Import-only build checks do not exercise
this GPU inference path.

To repair the already-built local image without repeating the Python installations:

```bash
docker build -f deploy/Dockerfile.voice-runtime-fix -t patient-listener-voice:compiler-fix .
```

End the browser session, stop the previous voice container with Ctrl+C, keep the
API running, and launch the repaired image:

```bash
PL_VOICE_IMAGE=patient-listener-voice:compiler-fix bash scripts/run_local_voice_container.sh
```

Repeat actual microphone/Stop and prepared-render checks. No model credentials or
paid calls are needed. The repaired image retains the same Python/model versions;
it adds only OS build tools and retains the non-root default user. The main
Dockerfile.voice includes the same permanent fix for future clean builds.

### Compiled-library mapping fix

The synthetic target-container check reproduced ASR's boosting-tree Triton failure:
cuda_utils.cpython-312-x86_64-linux-gnu.so failed to map a segment from its shared
object under /run/listener/triton. Docker's tmpfs defaults to noexec. The launcher
now explicitly enables exec on the UID-owned 0700 scratch-home tmpfs, allowing
Triton-generated shared libraries to load. Model caches and the database keep their
existing mounts. Restart the container after updating the launcher; no image rebuild
is required. The user subsequently confirmed working browser voice, hint playback
and Stop, then prepared-plan generation through the container: 2 plan items,
6 rendered clips and zero model calls. Prepared playback also passed. A separate
post-fix synthetic check was not reported. The repaired image is locally validated;
a fresh build of the consolidated Dockerfile and cloud acceptance remain open.

This milestone is committed locally at the user request; no remote push is authorized.
