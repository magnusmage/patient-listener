#!/usr/bin/env bash
# Linux-only local acceptance: preserves the working CPU process and DB location.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
image="${PL_VOICE_IMAGE:-patient-listener-voice:local}"
env_file="${PL_VOICE_ENV_FILE:-$project_dir/.env.split}"
if [[ "$env_file" != /* ]]; then env_file="$project_dir/$env_file"; fi
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Run this script on the Linux GPU host.' >&2; exit 1
fi
if [[ ! -f "$env_file" ]]; then
  echo 'The selected existing voice configuration file was not found.' >&2; exit 1
fi
env_file="$(realpath -e -- "$env_file")"
# Preserve the original SQLite launcher guard for its default configuration.
# A separate PostgreSQL configuration does not require a SQLite database.
if [[ "$env_file" == "$project_dir/.env.split" && ! -f "$project_dir/pl.db" ]]; then
  echo 'The default .env.split launch requires the existing pl.db.' >&2; exit 1
fi
if [[ "$(id -u)" == 0 ]]; then
  echo 'Run as the project owner, not root; use Docker group access.' >&2; exit 1
fi
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}"
hf_cache="${HF_HOME:-$cache_dir/huggingface}"
torch_cache="${TORCH_HOME:-$cache_dir/torch}"
nemo_cache="${NEMO_CACHE_DIR:-$HOME/.cache/torch/NeMo/NeMo_3.0.0}"
mkdir -p "$hf_cache" "$torch_cache" "$nemo_cache"
# Host networking retains both loopback URLs and the browser's existing origin.
# SQLite WAL needs its directory, not just a bind mount of the pl.db file.
# The project bind is for the existing DB/config, never the image's Python code.
exec docker run --rm --init --name patient-listener-voice-local \
  --runtime=nvidia --gpus all --network host --shm-size=2g --stop-timeout=60 \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$project_dir,dst=$project_dir" \
  --mount "type=bind,src=$env_file,dst=$env_file,readonly" \
  --mount "type=bind,src=$hf_cache,dst=/cache/huggingface" \
  --mount "type=bind,src=$torch_cache,dst=/cache/torch" \
  --mount "type=bind,src=$nemo_cache,dst=/cache/nemo" \
  --tmpfs "/run/listener:rw,exec,mode=0700,uid=$(id -u),gid=$(id -g)" \
  --env USER=listener --env LOGNAME=listener --env HOME=/run/listener \
  --env XDG_CONFIG_HOME=/run/listener/.config --env XDG_CACHE_HOME=/run/listener/.cache \
  --env MPLCONFIGDIR=/run/listener/matplotlib \
  --env TORCHINDUCTOR_CACHE_DIR=/run/listener/torchinductor \
  --env TRITON_CACHE_DIR=/run/listener/triton \
  --env PL_HOST=127.0.0.1 \
  "$image" python -m patient_listener.tools.services run voice \
  --env-file "$env_file"
