#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

download_model() {
  local repo_id="$1"
  local local_dir="$2"
  mkdir -p "$PROJECT_ROOT/$local_dir"
  echo "[download] $repo_id -> $local_dir"
  hf download "$repo_id" --local-dir "$PROJECT_ROOT/$local_dir"
}

require_command() {
  local name="$1"
  local hint="$2"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "[error] missing required command: $name"
    echo "[hint] $hint"
    exit 1
  fi
}

require_command hf "Install it with: pip install \"huggingface_hub[cli]\""

mkdir -p \
  "$PROJECT_ROOT/models/asr" \
  "$PROJECT_ROOT/models/aligner" \
  "$PROJECT_ROOT/models/emotion" \
  "$PROJECT_ROOT/models/diarization" \
  "$PROJECT_ROOT/models/embedding" \
  "$PROJECT_ROOT/models/separation" \
  "$PROJECT_ROOT/models/vad" \
  "$PROJECT_ROOT/models/tts"

download_model "Qwen/Qwen3-ASR-1.7B" "models/asr/Qwen3-ASR-1.7B"
download_model "Qwen/Qwen3-ForcedAligner-0.6B" "models/aligner/Qwen3-ForcedAligner-0.6B"
download_model "emotion2vec/emotion2vec_plus_large" "models/emotion/emotion2vec-large"
download_model "FunAudioLLM/Fun-CosyVoice3-0.5B-2512" "models/tts/Fun-CosyVoice3-0.5B"
download_model "BUT-FIT/diarizen-wavlm-large-s80-md-v2" "models/diarization/diarizen-wavlm-large-s80-md-v2"
download_model "hbredin/wespeaker-voxceleb-resnet34-LM" "models/embedding/wespeaker-voxceleb-resnet34-LM"

download_separator_model() {
  local model_filename="$1"
  if [[ -f "$PROJECT_ROOT/models/separation/$model_filename" ]]; then
    echo "[skip] models/separation/$model_filename already exists"
    return
  fi
  echo "[download] audio-separator $model_filename -> models/separation/ (via separator container)"
  (
    cd "$PROJECT_ROOT" && \
    MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps separator \
      audio-separator \
        -m "$model_filename" \
        --download_model_only \
        --model_file_dir models/separation
  )
}

require_command docker "Install Docker Desktop and run 'docker compose build separator' first."
download_separator_model "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
download_separator_model "MDX23C-8KFFT-InstVoc_HQ.ckpt"

download_vad_model() {
  local target_path="$PROJECT_ROOT/models/vad/silero_vad.jit"
  if [[ -f "$target_path" ]]; then
    echo "[skip] models/vad/silero_vad.jit already exists"
    return
  fi
  echo "[download] silero_vad.jit (v6.2.1) -> models/vad/"
  require_command curl "Install curl first."
  curl -fL -o "$target_path" \
    "https://github.com/snakers4/silero-vad/raw/v6.2.1/src/silero_vad/data/silero_vad.jit"
}

download_vad_model

echo "[ok] model setup completed"
