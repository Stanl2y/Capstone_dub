param(
    [string]$PythonExe = 'C:\Users\JONGWOONG\miniconda3\envs\movie\python.exe'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = 'C:\movie-dubbing-project'
$ReqFile = Join-Path $ProjectRoot 'requirements\runtime-single-env.txt'
$TempDir = Join-Path $ProjectRoot '.tmp-pip'
$CheckFile = Join-Path $ProjectRoot 'scripts\check_runtime_single_env.py'
$TtsModelDir = Join-Path $ProjectRoot 'models\tts\Fun-CosyVoice3-0.5B'
$SitePackages = Join-Path (Split-Path -Parent (Split-Path -Parent $PythonExe)) 'Lib\site-packages'
$WhisperPy = Join-Path $SitePackages 'whisper.py'
$WhisperDist = Join-Path $SitePackages 'whisper-1.1.10.dist-info'

Write-Host '[1/4] Removing wrong whisper package if present...'
& $PythonExe -m pip uninstall -y whisper
if (Test-Path $WhisperPy) {
    Remove-Item $WhisperPy -Force
}
if (Test-Path $WhisperDist) {
    Remove-Item $WhisperDist -Recurse -Force
}

Write-Host '[2/5] Upgrading pip tooling...'
& $PythonExe -m pip install -U pip wheel "setuptools<81"

Write-Host '[3/5] Installing consolidated runtime packages...'
New-Item -ItemType Directory -Force $TempDir | Out-Null
$env:TMP = $TempDir
$env:TEMP = $TempDir
& $PythonExe -m pip install -r $ReqFile

Write-Host '[4/5] Installing openai-whisper with no build isolation...'
& $PythonExe -m pip install --no-build-isolation openai-whisper==20231117

Write-Host '[5/5] Running full runtime preflight...'
& $PythonExe $CheckFile --model-dir $TtsModelDir

Write-Host 'Install finished.'
