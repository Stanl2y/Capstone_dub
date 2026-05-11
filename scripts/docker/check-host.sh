#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

required_paths=(
  "$PROJECT_ROOT/models/diarization/diarizen-wavlm-large-s80-md-v2"
  "$PROJECT_ROOT/models/emotion/emotion2vec-large"
  "$PROJECT_ROOT/models/asr/Qwen3-ASR-1.7B"
)

tts_candidate_paths=(
  "$PROJECT_ROOT/models/tts/Fun-CosyVoice3-0.5B"
)

echo "[check] project root: $PROJECT_ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "[error] docker CLI is not available in this shell."
  echo "[hint] If you use WSL2, enable Docker Desktop WSL integration for this distro."
  exit 1
fi

compose_output=""
if ! compose_output="$(docker compose version 2>&1)"; then
  echo "[error] docker compose is not available or the docker CLI is disconnected."
  echo "$compose_output"
  echo "[hint] If you use WSL2, start Docker Desktop and enable WSL integration for this distro."
  exit 1
fi

daemon_output=""
if ! daemon_output="$(docker info 2>&1)"; then
  echo "[error] docker daemon is not reachable."
  echo "$daemon_output"
  echo "[hint] Start Docker Desktop or the Docker daemon first."
  exit 1
fi

for path in "${required_paths[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "[error] missing required path: $path"
    exit 1
  fi
  echo "[ok] $path"
done

found_tts_path=false
for path in "${tts_candidate_paths[@]}"; do
  if [[ -e "$path" ]]; then
    echo "[ok] found local TTS path: $path"
    found_tts_path=true
  fi
done

if [[ "$found_tts_path" != true ]]; then
  echo "[warn] no known local TTS model path was found under $PROJECT_ROOT/models/tts"
  echo "[warn] build/up can still succeed, but runtime execution will fail until a supported TTS model is available."
fi

for path in \
  "$PROJECT_ROOT/third_party/CosyVoice"
do
  if [[ -e "$path" ]]; then
    echo "[ok] optional repo present: $path"
  fi
done

echo "[ok] docker host looks ready"
