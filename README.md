# Movie Dubbing Project

Local movie dubbing pipeline for source separation, diarization, ASR, translation, and CosyVoice-based Korean dubbing.
Source speech emotion extraction is handled with `emotion2vec_plus_large` and saved into the timeline metadata.

## What Goes To GitHub

Commit the code, configs, docs, and scripts.

Do not commit local runtime artifacts:

- `models/`
- `audio/`
- `input/`
- `output/`
- `dub/`
- `chunks/`
- `logs/`
- `meta/`
- `.env`

Those paths are ignored in `.gitignore`.

## Environment

- Python with `pip`
- Git
- Git LFS
- Hugging Face CLI via `pip install "huggingface_hub[cli]"`
- Docker Desktop or Docker Engine for the Docker-based pipeline

If a model repository is gated, authenticate first:

```bash
hf auth login
```

## Model Setup

The repository does not include model weights. Download them locally after cloning.

### Linux Or macOS

```bash
pip install "huggingface_hub[cli]"
bash ./download_models.sh
```

### Windows PowerShell

```powershell
pip install "huggingface_hub[cli]"
powershell -ExecutionPolicy Bypass -File .\scripts\setup_models.ps1
```

The setup scripts download models into the local paths expected by the checked-in configs:

- `models/asr/Qwen3-ASR-1.7B`
- `models/aligner/Qwen3-ForcedAligner-0.6B`
- `models/emotion/emotion2vec-large`
- `models/tts/Fun-CosyVoice3-0.5B`
- `models/diarization/pyannote-community-1`

## Secrets

Copy `.env.example` to `.env` and fill in your values.

`.env` is local-only and should never be committed.

## Docker Example

Build the CosyVoice-only Docker services:

```powershell
docker compose build
```

Run the pipeline helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\docker\run_pipeline.ps1 -Config .\configs\cosyvoice3-docker-draft.json
```

Run only the TTS and later stages after earlier artifacts already exist:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\docker\run_pipeline.ps1 -Config .\configs\cosyvoice3-docker-draft.json -FromStep build_timeline -ToStep mux
```

Run only emotion extraction after chunks already exist:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\docker\run_pipeline.ps1 -Config .\configs\cosyvoice3-docker-draft.json -FromStep extract_emotion -ToStep extract_emotion
```

## Publish To GitHub

After confirming the large local folders are ignored:

```powershell
git init
git branch -M main
git add .
git status --short
git commit -m "Initial commit"
git remote add origin https://github.com/<YOUR_ID>/<YOUR_REPO>.git
git push -u origin main
```

If you accidentally staged generated folders before updating `.gitignore`, remove them from the index and try again:

```powershell
git rm -r --cached models audio input output dub chunks logs meta bef .external
```

## References

- Hugging Face CLI auth: https://huggingface.co/docs/huggingface_hub/guides/cli#hf-auth-login
- Hugging Face file downloads: https://huggingface.co/docs/huggingface_hub/package_reference/file_download
- GitHub large file limits: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
