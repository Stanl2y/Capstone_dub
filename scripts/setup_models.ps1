[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Require-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Hint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name. $Hint"
    }
}

function Download-Model {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoId,
        [Parameter(Mandatory = $true)]
        [string]$LocalDir
    )

    $ResolvedDir = Join-Path $ProjectRoot $LocalDir
    New-Item -ItemType Directory -Force -Path $ResolvedDir | Out-Null
    Write-Host "[download] $RepoId -> $LocalDir"
    & hf download $RepoId --local-dir $ResolvedDir
}

Require-Command -Name "hf" -Hint 'Install it with: pip install "huggingface_hub[cli]"'

@(
    "models/asr",
    "models/aligner",
    "models/emotion",
    "models/diarization",
    "models/embedding",
    "models/separation",
    "models/vad",
    "models/tts"
) | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $_) | Out-Null
}

Download-Model -RepoId "Qwen/Qwen3-ASR-1.7B" -LocalDir "models/asr/Qwen3-ASR-1.7B"
Download-Model -RepoId "microsoft/VibeVoice-ASR-HF" -LocalDir "models/asr/VibeVoice-ASR-HF"
Download-Model -RepoId "Qwen/Qwen3-ForcedAligner-0.6B" -LocalDir "models/aligner/Qwen3-ForcedAligner-0.6B"
Download-Model -RepoId "emotion2vec/emotion2vec_plus_large" -LocalDir "models/emotion/emotion2vec-large"
Download-Model -RepoId "FunAudioLLM/Fun-CosyVoice3-0.5B-2512" -LocalDir "models/tts/Fun-CosyVoice3-0.5B"
Download-Model -RepoId "BUT-FIT/diarizen-wavlm-large-s80-md-v2" -LocalDir "models/diarization/diarizen-wavlm-large-s80-md-v2"
Download-Model -RepoId "hbredin/wespeaker-voxceleb-resnet34-LM" -LocalDir "models/embedding/wespeaker-voxceleb-resnet34-LM"
Download-Model -RepoId "speechbrain/spkrec-ecapa-voxceleb" -LocalDir "models/embedding/spkrec-ecapa-voxceleb"

function Download-SeparatorModel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModelFilename
    )

    $TargetPath = Join-Path $ProjectRoot (Join-Path "models/separation" $ModelFilename)
    if (Test-Path $TargetPath) {
        Write-Host "[skip] models/separation/$ModelFilename already exists"
        return
    }
    Write-Host "[download] audio-separator $ModelFilename -> models/separation/ (via separator container)"
    Push-Location $ProjectRoot
    try {
        & docker compose run --rm --no-deps separator `
            audio-separator `
                -m $ModelFilename `
                --download_model_only `
                --model_file_dir "models/separation"
    }
    finally {
        Pop-Location
    }
}

Require-Command -Name "docker" -Hint "Install Docker Desktop and run 'docker compose build separator' first."
Download-SeparatorModel -ModelFilename "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
Download-SeparatorModel -ModelFilename "MDX23C-8KFFT-InstVoc_HQ.ckpt"

function Download-VadModel {
    $TargetPath = Join-Path $ProjectRoot "models/vad/silero_vad.jit"
    if (Test-Path $TargetPath) {
        Write-Host "[skip] models/vad/silero_vad.jit already exists"
        return
    }
    Write-Host "[download] silero_vad.jit (v6.2.1) -> models/vad/"
    Invoke-WebRequest `
        -Uri "https://github.com/snakers4/silero-vad/raw/v6.2.1/src/silero_vad/data/silero_vad.jit" `
        -OutFile $TargetPath `
        -UseBasicParsing
}

Download-VadModel

Write-Host "[ok] model setup completed"
