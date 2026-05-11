# webapp dev — webapp-backend + webapp-frontend 만 기동.
# 기존 GPU 서비스(controller/demucs/speaker/tts-cosyvoice) 는 첫 파이프라인 실행 시 자동 기동되므로
# 미리 띄우고 싶으면 scripts\docker\up.sh 또는 docker compose up -d 사용.
[CmdletBinding()]
param(
    [string]$ProjectName = "movie-dubbing-project",
    [string]$ComposeFile = "docker-compose.yml",
    [switch]$Build,
    [switch]$Detach
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$composeArgs = @("-p", $ProjectName, "-f", $ComposeFile)

if ($Build) {
    Write-Host "[dev] webapp-backend / webapp-frontend 이미지 빌드..." -ForegroundColor Cyan
    & docker compose @composeArgs build webapp-backend webapp-frontend
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
}

$upArgs = @("up")
if ($Detach) { $upArgs += "-d" }
$upArgs += @("webapp-backend", "webapp-frontend")

Write-Host "[dev] webapp-backend (8000) + webapp-frontend (5173) 기동..." -ForegroundColor Cyan
& docker compose @composeArgs @upArgs
