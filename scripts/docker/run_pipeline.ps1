[CmdletBinding()]
param(
    [string]$Config = "configs/cosyvoice3-docker-draft.json",
    [string]$InputVideo = "",
    [ValidateSet("extract_audio", "separate_audio", "diarize", "rttm_to_json", "merge_chunks", "cut_chunks", "extract_emotion", "run_asr", "translate", "build_timeline", "generate_tts_instructions", "run_tts", "validate_tts", "compose_audio", "mux")]
    [string]$FromStep = "extract_audio",
    [ValidateSet("extract_audio", "separate_audio", "diarize", "rttm_to_json", "merge_chunks", "cut_chunks", "extract_emotion", "run_asr", "translate", "build_timeline", "generate_tts_instructions", "run_tts", "validate_tts", "compose_audio", "mux")]
    [string]$ToStep = "mux",
    [string]$ProjectName = "movie-dubbing-project",
    [string]$ComposeFile = "docker-compose.yml",
    [switch]$NoStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$StepOrder = @(
    "extract_audio",
    "separate_audio",
    "diarize",
    "rttm_to_json",
    "merge_chunks",
    "cut_chunks",
    "extract_emotion",
    "run_asr",
    "translate",
    "build_timeline",
    "generate_tts_instructions",
    "run_tts",
    "validate_tts",
    "compose_audio",
    "mux"
)

function Get-Bool {
    param(
        $Value,
        [bool]$Default = $false
    )

    if ($null -eq $Value) {
        return $Default
    }
    if ($Value -is [bool]) {
        return $Value
    }

    $text = "$Value".Trim().ToLowerInvariant()
    if ($text -in @("1", "true", "yes", "on")) {
        return $true
    }
    if ($text -in @("0", "false", "no", "off")) {
        return $false
    }
    return $Default
}

function Get-ObjectPropertyValue {
    param(
        $Object,
        [string]$Name,
        $Default = $null
    )

    if ($null -eq $Object) {
        return $Default
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $Default
    }

    return $property.Value
}

function Set-ObjectPropertyValue {
    param(
        $Object,
        [string]$Name,
        $Value
    )

    if ($null -eq $Object) {
        return
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
        return
    }

    $property.Value = $Value
}

function Convert-ToPathToken {
    param(
        [string]$Value,
        [string]$Default = "item"
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Default
    }

    $text = $Value.Trim()
    $text = [regex]::Replace($text, '[<>:"/\\|?*\x00-\x1F]+', "_")
    $text = [regex]::Replace($text, '\s+', "_")
    $text = [regex]::Replace($text, '_+', "_")
    $text = $text.Trim(' ', '.', '_')

    if ([string]::IsNullOrWhiteSpace($text)) {
        return $Default
    }

    return $text
}

function Expand-TemplateValue {
    param(
        [string]$Value,
        [hashtable]$Placeholders
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }

    $expanded = $Value
    foreach ($key in $Placeholders.Keys) {
        $expanded = $expanded.Replace("{$key}", [string]$Placeholders[$key])
    }

    return $expanded
}

function Expand-ConfigTemplates {
    param($ConfigData)

    $inputVideo = [string](Get-ObjectPropertyValue -Object $ConfigData -Name "input_video" -Default "")
    $inputLeaf = if ([string]::IsNullOrWhiteSpace($inputVideo)) { "input.mp4" } else { Split-Path -Leaf $inputVideo }
    $inputStem = [System.IO.Path]::GetFileNameWithoutExtension($inputLeaf)
    $ttsEngine = ([string](Get-ObjectPropertyValue -Object (Get-ObjectPropertyValue -Object $ConfigData -Name "tts") -Name "engine" -Default "cosyvoice")).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($ttsEngine)) {
        $ttsEngine = "cosyvoice"
    }

    $placeholders = @{
        input_stem = Convert-ToPathToken -Value $inputStem -Default "input"
        tts_engine = Convert-ToPathToken -Value $ttsEngine -Default "tts"
    }

    $inputVideoValue = Get-ObjectPropertyValue -Object $ConfigData -Name "input_video"
    if ($inputVideoValue -is [string]) {
        Set-ObjectPropertyValue -Object $ConfigData -Name "input_video" -Value (Expand-TemplateValue -Value $inputVideoValue -Placeholders $placeholders)
    }

    $paths = Get-ObjectPropertyValue -Object $ConfigData -Name "paths"
    if ($null -ne $paths) {
        foreach ($property in $paths.PSObject.Properties) {
            if ($property.Value -is [string]) {
                $property.Value = Expand-TemplateValue -Value ([string]$property.Value) -Placeholders $placeholders
            }
        }
    }

    $audio = Get-ObjectPropertyValue -Object $ConfigData -Name "audio"
    if ($null -ne $audio) {
        $chunkSource = Get-ObjectPropertyValue -Object $audio -Name "chunk_source"
        if ($chunkSource -is [string]) {
            Set-ObjectPropertyValue -Object $audio -Name "chunk_source" -Value (Expand-TemplateValue -Value ([string]$chunkSource) -Placeholders $placeholders)
        }
    }

    return $ConfigData
}

function Add-Option {
    param(
        [System.Collections.Generic.List[string]]$TargetList,
        [string]$Name,
        $Value
    )

    if ($null -eq $Value) {
        return
    }

    $text = "$Value"
    if ([string]::IsNullOrWhiteSpace($text)) {
        return
    }

    $TargetList.Add($Name)
    $TargetList.Add($text)
}

function Add-Flag {
    param(
        [System.Collections.Generic.List[string]]$TargetList,
        [string]$Name,
        [bool]$Enabled
    )

    if ($Enabled) {
        $TargetList.Add($Name)
    }
}

function Add-Arguments {
    param(
        [System.Collections.Generic.List[string]]$TargetList,
        [System.Collections.IEnumerable]$Values
    )

    foreach ($value in $Values) {
        $TargetList.Add("$value")
    }
}

function Quote-Arg {
    param([string]$Value)

    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Invoke-Docker {
    param(
        [string[]]$Arguments,
        [string]$LogFile,
        [string]$Description
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $commandText = "docker " + (($Arguments | ForEach-Object { Quote-Arg $_ }) -join " ")

    Write-Host "[$timestamp] $Description"
    Add-Content -Path $LogFile -Value "[$timestamp] $Description"
    Add-Content -Path $LogFile -Value $commandText

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath "docker" -ArgumentList $Arguments -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $exitCode = $process.ExitCode

        $stdoutText = [System.IO.File]::ReadAllText($stdoutPath)
        if (-not [string]::IsNullOrEmpty($stdoutText)) {
            Write-Host $stdoutText -NoNewline
            Add-Content -Path $LogFile -Value $stdoutText
        }

        $stderrText = [System.IO.File]::ReadAllText($stderrPath)
        if (-not [string]::IsNullOrEmpty($stderrText)) {
            Write-Host $stderrText -NoNewline
            Add-Content -Path $LogFile -Value $stderrText
        }
    }
    finally {
        Remove-Item -Path $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
    }

    if ($exitCode -ne 0) {
        throw "Failed: $Description (exit code $exitCode). See $LogFile"
    }
}

function Get-SelectedSteps {
    param(
        [string[]]$AllSteps,
        [string]$StartStep,
        [string]$EndStep
    )

    $startIndex = [Array]::IndexOf($AllSteps, $StartStep)
    $endIndex = [Array]::IndexOf($AllSteps, $EndStep)

    if ($startIndex -lt 0) {
        throw "Unknown from-step: $StartStep"
    }
    if ($endIndex -lt 0) {
        throw "Unknown to-step: $EndStep"
    }
    if ($endIndex -lt $startIndex) {
        throw "to-step must be after from-step"
    }

    return $AllSteps[$startIndex..$endIndex]
}

function Get-RequiredServices {
    param(
        [string[]]$SelectedSteps,
        [bool]$UseSeparator,
        [string]$TtsService
    )

    $services = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($step in $SelectedSteps) {
        switch ($step) {
            "extract_audio" { [void]$services.Add("controller") }
            "separate_audio" {
                if ($UseSeparator) {
                    [void]$services.Add("separator")
                }
                else {
                    [void]$services.Add("controller")
                }
            }
            "diarize" { [void]$services.Add("diarizer") }
            "rttm_to_json" { [void]$services.Add("controller") }
            "merge_chunks" { [void]$services.Add("controller") }
            "cut_chunks" { [void]$services.Add("controller") }
            "extract_emotion" { [void]$services.Add("speaker") }
            "run_asr" { [void]$services.Add("speaker") }
            "translate" { [void]$services.Add("controller") }
            "build_timeline" { [void]$services.Add("controller") }
            "generate_tts_instructions" { [void]$services.Add("controller") }
            "run_tts" { [void]$services.Add($TtsService) }
            "validate_tts" { [void]$services.Add("speaker") }
            "compose_audio" { [void]$services.Add("controller") }
            "mux" { [void]$services.Add("controller") }
        }
    }

    return [string[]](@($services) | Sort-Object)
}

function Resolve-ProjectValue {
    param(
        [string]$ProjectRootPath,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRootPath $Value
}

function Ensure-ParentPath {
    param(
        [string]$ProjectRootPath,
        [string]$Value
    )

    $resolved = Resolve-ProjectValue -ProjectRootPath $ProjectRootPath -Value $Value
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        return
    }

    $parent = Split-Path -Parent $resolved
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Ensure-DirectoryPath {
    param(
        [string]$ProjectRootPath,
        [string]$Value
    )

    $resolved = Resolve-ProjectValue -ProjectRootPath $ProjectRootPath -Value $Value
    if (-not [string]::IsNullOrWhiteSpace($resolved)) {
        New-Item -ItemType Directory -Force -Path $resolved | Out-Null
    }
}

function Ensure-ProjectLayout {
    param(
        [string]$ProjectRootPath,
        $ConfigData
    )

    foreach ($key in @(
        "raw_audio",
        "dialogue_audio",
        "bgm_audio",
        "diarization_rttm",
        "diarization_json",
        "diarization_stabilized_json",
        "speaker_chunks_json",
        "emotion_json",
        "asr_json",
        "translated_json",
        "master_timeline_json",
        "final_dub_audio",
        "output_video"
    )) {
        $candidate = Get-ObjectPropertyValue -Object $ConfigData.paths -Name $key
        if ($candidate) {
            Ensure-ParentPath -ProjectRootPath $ProjectRootPath -Value "$candidate"
        }
    }

    foreach ($key in @("chunks_dir", "dub_dir")) {
        $candidate = Get-ObjectPropertyValue -Object $ConfigData.paths -Name $key
        if ($candidate) {
            Ensure-DirectoryPath -ProjectRootPath $ProjectRootPath -Value "$candidate"
        }
    }

    foreach ($folder in @("input", "audio", "meta", "chunks", "dub", "output", "third_party", "docs")) {
        Ensure-DirectoryPath -ProjectRootPath $ProjectRootPath -Value $folder
    }
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposePath = (Resolve-Path (Join-Path $ProjectRoot $ComposeFile)).Path
$ConfigPath = (Resolve-Path (Join-Path $ProjectRoot $Config)).Path

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker CLI is not available in this shell."
}

$configData = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
if (-not [string]::IsNullOrWhiteSpace($InputVideo)) {
    Set-ObjectPropertyValue -Object $configData -Name "input_video" -Value $InputVideo
}
$configData = Expand-ConfigTemplates -ConfigData $configData
Ensure-ProjectLayout -ProjectRootPath $ProjectRoot -ConfigData $configData

$selectedSteps = Get-SelectedSteps -AllSteps $StepOrder -StartStep $FromStep -EndStep $ToStep
$useSeparator = Get-Bool (Get-ObjectPropertyValue -Object $configData.pipeline -Name "use_separator")
$ttsEngine = ([string](Get-ObjectPropertyValue -Object $configData.tts -Name 'engine' -Default 'cosyvoice')).Trim().ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($ttsEngine)) {
    $ttsEngine = "cosyvoice"
}

$ttsService = switch ($ttsEngine) {
    "cosyvoice" { "tts-cosyvoice" }
    default { throw "Unsupported TTS engine after cleanup: $ttsEngine" }
}
$requiredServices = Get-RequiredServices -SelectedSteps $selectedSteps -UseSeparator $useSeparator -TtsService $ttsService

$logRoot = Join-Path $ProjectRoot "logs\docker-pipeline"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = Join-Path $logRoot $runStamp
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$summaryLog = Join-Path $logDir "00_summary.log"

$composeBase = [System.Collections.Generic.List[string]]::new()
$composeBase.Add("compose")
$composeBase.Add("-p")
$composeBase.Add($ProjectName)
$composeBase.Add("-f")
$composeBase.Add($ComposePath)

Add-Content -Path $summaryLog -Value "Project root: $ProjectRoot"
Add-Content -Path $summaryLog -Value "Compose file: $ComposePath"
Add-Content -Path $summaryLog -Value "Config file: $ConfigPath"
Add-Content -Path $summaryLog -Value "Selected steps: $($selectedSteps -join ', ')"
Add-Content -Path $summaryLog -Value "Logs: $logDir"

if (-not $NoStart) {
    $upArgs = @($composeBase.ToArray()) + @("up", "-d") + $requiredServices
    Invoke-Docker -Arguments $upArgs -LogFile (Join-Path $logDir "01_up.log") -Description "Starting required services: $($requiredServices -join ', ')"
}

$paths = $configData.paths
$audio = $configData.audio
$models = $configData.models
$runtime = $configData.runtime
$chunking = $configData.chunking
$diarization = Get-ObjectPropertyValue -Object $configData -Name "diarization"
$emotion = Get-ObjectPropertyValue -Object $configData -Name "emotion"
$translation = $configData.translation
$tts = $configData.tts
$ttsInstruction = Get-ObjectPropertyValue -Object $tts -Name "instruction"

$extractSampleRate = if ($useSeparator) { Get-ObjectPropertyValue -Object $audio -Name "source_sample_rate" -Default 44100 } else { Get-ObjectPropertyValue -Object $audio -Name "sample_rate" -Default 16000 }
$extractChannels = if ($useSeparator) { Get-ObjectPropertyValue -Object $audio -Name "source_channels" -Default 2 } else { Get-ObjectPropertyValue -Object $audio -Name "channels" -Default 1 }
$chunkSource = Get-ObjectPropertyValue -Object $audio -Name "chunk_source" -Default (Get-ObjectPropertyValue -Object $paths -Name "dialogue_audio")
$translationMode = [string](Get-ObjectPropertyValue -Object $translation -Name 'mode' -Default 'copy_source')
$sourceLanguage = [string](Get-ObjectPropertyValue -Object $translation -Name 'source_language' -Default 'English')
$targetLanguage = [string](Get-ObjectPropertyValue -Object $translation -Name 'target_language' -Default '')
$translationEnvFile = [string](Get-ObjectPropertyValue -Object $translation -Name 'env_file' -Default '.env')
$timeoutSec = Get-ObjectPropertyValue -Object $translation -Name "timeout_sec" -Default 60
$translationContextRefine = Get-Bool (Get-ObjectPropertyValue -Object $translation -Name "context_refine") $true
$translationContextBatchSize = Get-ObjectPropertyValue -Object $translation -Name "context_batch_size" -Default 12
$translationDurationControl = Get-Bool (Get-ObjectPropertyValue -Object $translation -Name "duration_control") $true
$translationMaxBudgetRewrites = Get-ObjectPropertyValue -Object $translation -Name "max_budget_rewrites" -Default 2
$ttsInstructionMode = [string](Get-ObjectPropertyValue -Object $ttsInstruction -Name "mode" -Default "vectorengine_gemini")
$ttsInstructionEnvFile = [string](Get-ObjectPropertyValue -Object $ttsInstruction -Name "env_file" -Default $translationEnvFile)
$ttsInstructionTimeoutSec = Get-ObjectPropertyValue -Object $ttsInstruction -Name "timeout_sec" -Default $timeoutSec
$ttsInstructionBatchSize = Get-ObjectPropertyValue -Object $ttsInstruction -Name "batch_size" -Default 6
$ttsInstructionSkipExisting = Get-Bool (Get-ObjectPropertyValue -Object $ttsInstruction -Name "skip_existing") $true
$ttsInstructionFallbackOnError = Get-Bool (Get-ObjectPropertyValue -Object $ttsInstruction -Name "fallback_on_error") $true
$device = [string](Get-ObjectPropertyValue -Object $runtime -Name 'device' -Default 'cuda:0')
$dtype = [string](Get-ObjectPropertyValue -Object $runtime -Name 'dtype' -Default 'float16')
$gapThreshold = Get-ObjectPropertyValue -Object $chunking -Name "speaker_merge_gap_sec" -Default 0.5
$minChunkSec = Get-ObjectPropertyValue -Object $chunking -Name "min_chunk_sec" -Default 0.0
$maxChunkSec = Get-ObjectPropertyValue -Object $chunking -Name "max_chunk_sec" -Default 0.0
$diarizationMinSpeakers = Get-ObjectPropertyValue -Object $diarization -Name "min_speakers"
$diarizationMaxSpeakers = Get-ObjectPropertyValue -Object $diarization -Name "max_speakers"
$diarizationAhcThreshold = Get-ObjectPropertyValue -Object $diarization -Name "ahc_threshold"
$diarizationFa = Get-ObjectPropertyValue -Object $diarization -Name "fa"
$diarizationFb = Get-ObjectPropertyValue -Object $diarization -Name "fb"
$diarizationLdaDim = Get-ObjectPropertyValue -Object $diarization -Name "lda_dim"
$diarizationMaxIters = Get-ObjectPropertyValue -Object $diarization -Name "max_iters"
$diarizationMethod = Get-ObjectPropertyValue -Object $diarization -Name "method"
$diarizationMinClusterSize = Get-ObjectPropertyValue -Object $diarization -Name "min_cluster_size"
$diarizationSegDuration = Get-ObjectPropertyValue -Object $diarization -Name "seg_duration"
$diarizationSegmentationStep = Get-ObjectPropertyValue -Object $diarization -Name "segmentation_step"
$stabilization = Get-ObjectPropertyValue -Object $diarization -Name "stabilization"
$stabilizationEnabled = Get-Bool (Get-ObjectPropertyValue -Object $stabilization -Name "enabled") $false
$stabilizedDiarizationJson = [string](Get-ObjectPropertyValue -Object $paths -Name "diarization_stabilized_json" -Default (Get-ObjectPropertyValue -Object $paths -Name "diarization_json"))
$diarizationJsonForMerge = if ($stabilizationEnabled) { $stabilizedDiarizationJson } else { [string](Get-ObjectPropertyValue -Object $paths -Name "diarization_json") }
$stabilizationSameSpeakerGapSec = Get-ObjectPropertyValue -Object $stabilization -Name "same_speaker_gap_sec" -Default 0.1
$stabilizationBridgeMaxSec = Get-ObjectPropertyValue -Object $stabilization -Name "bridge_max_sec" -Default 0.4
$stabilizationBridgeGapSec = Get-ObjectPropertyValue -Object $stabilization -Name "bridge_gap_sec" -Default 0.25
$stabilizationTinySegmentSec = Get-ObjectPropertyValue -Object $stabilization -Name "tiny_segment_sec" -Default 0.12
$stabilizationAbsorbGapSec = Get-ObjectPropertyValue -Object $stabilization -Name "absorb_gap_sec" -Default 0.25
$stabilizationMaxPasses = Get-ObjectPropertyValue -Object $stabilization -Name "max_passes" -Default 5
$emotionModel = [string](Get-ObjectPropertyValue -Object $models -Name "emotion" -Default "iic/emotion2vec_plus_large")
$emotionBackend = [string](Get-ObjectPropertyValue -Object $emotion -Name "backend" -Default "funasr")
$emotionSkipExisting = Get-Bool (Get-ObjectPropertyValue -Object $emotion -Name "skip_existing") $true
$minPromptSec = Get-ObjectPropertyValue -Object $tts -Name "min_prompt_sec" -Default 1.2
$ttsSpeed = Get-ObjectPropertyValue -Object $tts -Name "speed" -Default 1.0
$referenceMode = ([string](Get-ObjectPropertyValue -Object $tts -Name 'reference_mode' -Default 'auto')).Trim().ToLowerInvariant()
$stylePriority = ([string](Get-ObjectPropertyValue -Object $tts -Name 'style_priority' -Default 'instruction')).Trim().ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($stylePriority)) { $stylePriority = 'instruction' }
$skipExisting = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "skip_existing") $true
$stream = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "stream")
$fitToDuration = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "fit_to_duration")
$durationFitMinTempo = Get-ObjectPropertyValue -Object $tts -Name "duration_fit_min_tempo" -Default 0.85
$durationFitMaxTempo = Get-ObjectPropertyValue -Object $tts -Name "duration_fit_max_tempo" -Default 1.2
$durationFitTrimOverlong = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "duration_fit_trim_overlong") $false
$trimSilence = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "trim_silence") $false
$silenceTrimThresholdDbfs = Get-ObjectPropertyValue -Object $tts -Name "silence_trim_threshold_dbfs" -Default -45.0
$maxLeadingSilenceSec = Get-ObjectPropertyValue -Object $tts -Name "max_leading_silence_sec" -Default 0.1
$maxTrailingSilenceSec = Get-ObjectPropertyValue -Object $tts -Name "max_trailing_silence_sec" -Default 0.2
$capRiskySelfReference = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "cap_risky_self_reference") $true
$promptCapMaxSec = Get-ObjectPropertyValue -Object $tts -Name "prompt_cap_max_sec" -Default 4.5
$compactTimeline = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "compact_timeline")
$ttsValidation = Get-ObjectPropertyValue -Object $tts -Name "validation"
$ttsValidationEnabled = Get-Bool (Get-ObjectPropertyValue -Object $ttsValidation -Name "enabled") $true
$ttsValidationMarkStale = Get-Bool (Get-ObjectPropertyValue -Object $ttsValidation -Name "mark_stale_on_fail") $true
$ttsValidationFailOnError = Get-Bool (Get-ObjectPropertyValue -Object $ttsValidation -Name "fail_on_error") $false
$ttsValidationLanguage = [string](Get-ObjectPropertyValue -Object $ttsValidation -Name "language" -Default $targetLanguage)
$defaultFinalSampleRate = if ($useSeparator) { Get-ObjectPropertyValue -Object $audio -Name "source_sample_rate" -Default 44100 } else { Get-ObjectPropertyValue -Object $audio -Name "sample_rate" -Default 16000 }
$defaultFinalChannels = if ($useSeparator) { Get-ObjectPropertyValue -Object $audio -Name "source_channels" -Default 2 } else { Get-ObjectPropertyValue -Object $audio -Name "channels" -Default 1 }
$finalSampleRate = Get-ObjectPropertyValue -Object $audio -Name "final_sample_rate" -Default $defaultFinalSampleRate
$finalChannels = Get-ObjectPropertyValue -Object $audio -Name "final_channels" -Default $defaultFinalChannels
$backgroundGain = Get-ObjectPropertyValue -Object $audio -Name "background_gain" -Default 1.0
$dubGain = Get-ObjectPropertyValue -Object $audio -Name "dub_gain" -Default 1.0
$targetPeakDbfs = Get-ObjectPropertyValue -Object $audio -Name "target_peak_dbfs" -Default -1.0
$finalCodec = [string](Get-ObjectPropertyValue -Object $audio -Name "final_codec" -Default "aac")
$finalBitrate = [string](Get-ObjectPropertyValue -Object $audio -Name "final_bitrate" -Default "192k")
$masterTimelineDir = [System.IO.Path]::GetDirectoryName([string]$paths.master_timeline_json)
if ([string]::IsNullOrWhiteSpace($masterTimelineDir)) {
    $masterTimelineDir = "meta"
}
$ttsValidationJsonDefault = (($masterTimelineDir -replace '\\', '/') + "/tts_validation_$ttsEngine.json")
$ttsValidationJson = [string](Get-ObjectPropertyValue -Object $paths -Name "tts_validation_json" -Default $ttsValidationJsonDefault)
$passthroughOnCopySource = Get-Bool (Get-ObjectPropertyValue -Object $tts -Name "passthrough_on_copy_source") $true
$passthroughSourceAudio = $passthroughOnCopySource -and ($translationMode -eq "copy_source")
$useCrossLingual = (-not [string]::IsNullOrWhiteSpace($sourceLanguage)) -and (-not [string]::IsNullOrWhiteSpace($targetLanguage)) -and ($sourceLanguage.Trim().ToLowerInvariant() -ne $targetLanguage.Trim().ToLowerInvariant())
$dubRuntime = [ordered]@{
    engine = $ttsEngine
    model_dir = [string](Get-ObjectPropertyValue -Object $models -Name "tts" -Default "")
    target_language = $targetLanguage
    reference_mode = $referenceMode
    min_prompt_sec = $minPromptSec
    fit_to_duration = $fitToDuration
    passthrough_source_audio = $passthroughSourceAudio
    use_cross_lingual = $useCrossLingual
    system_prompt = [string](Get-ObjectPropertyValue -Object $tts -Name "system_prompt" -Default "")
    speed = [double](Get-ObjectPropertyValue -Object $tts -Name "speed" -Default 1.0)
    cap_risky_self_reference = $capRiskySelfReference
    prompt_cap_max_sec = [double]$promptCapMaxSec
    duration_fit_trim_overlong = $durationFitTrimOverlong
    trim_silence = $trimSilence
    silence_trim_threshold_dbfs = [double]$silenceTrimThresholdDbfs
    max_leading_silence_sec = [double]$maxLeadingSilenceSec
    max_trailing_silence_sec = [double]$maxTrailingSilenceSec
}
$dubRuntimeJson = $dubRuntime | ConvertTo-Json -Compress
$dubRuntimePath = Join-Path $logDir "dub_runtime.json"
$dubRuntimeJson | Set-Content -Path $dubRuntimePath -Encoding UTF8
$dubRuntimeProjectPath = "logs/docker-pipeline/$runStamp/dub_runtime.json"

$stepIndex = 1
foreach ($step in $selectedSteps) {
    $innerArgs = [System.Collections.Generic.List[string]]::new()
    $service = ""

    switch ($step) {
        "extract_audio" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/extract_audio.py", (Get-ObjectPropertyValue -Object $configData -Name "input_video"), (Get-ObjectPropertyValue -Object $paths -Name "raw_audio"), "--sample-rate", "$extractSampleRate", "--channels", "$extractChannels")
        }
        "separate_audio" {
            $service = if ($useSeparator) { "separator" } else { "controller" }
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/separate_audio.py", (Get-ObjectPropertyValue -Object $paths -Name "raw_audio"), (Get-ObjectPropertyValue -Object $paths -Name "dialogue_audio"))
            Add-Option -TargetList $innerArgs -Name "--bgm-wav" -Value (Get-ObjectPropertyValue -Object $paths -Name "bgm_audio")
            Add-Flag -TargetList $innerArgs -Name "--no-separator" -Enabled (-not $useSeparator)
            $ensembleModelDir = [string](Get-ObjectPropertyValue -Object (Get-ObjectPropertyValue -Object $audio -Name "subtractive_ensemble") -Name "model_dir" -Default "models/separation")
            Add-Option -TargetList $innerArgs -Name "--ensemble-model-dir" -Value $ensembleModelDir
            Add-Option -TargetList $innerArgs -Name "--device" -Value $device
        }
        "diarize" {
            $service = "diarizer"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/diarize.py", "$($paths.dialogue_audio)", "$($paths.diarization_rttm)", "--model-dir", "$($models.diarization)", "--embedding-model-dir", "$($models.diarization_embedding)", "--device", $device)
            Add-Option -TargetList $innerArgs -Name "--min-speakers" -Value $diarizationMinSpeakers
            Add-Option -TargetList $innerArgs -Name "--max-speakers" -Value $diarizationMaxSpeakers
            Add-Option -TargetList $innerArgs -Name "--ahc-threshold" -Value $diarizationAhcThreshold
            Add-Option -TargetList $innerArgs -Name "--fa" -Value $diarizationFa
            Add-Option -TargetList $innerArgs -Name "--fb" -Value $diarizationFb
            Add-Option -TargetList $innerArgs -Name "--lda-dim" -Value $diarizationLdaDim
            Add-Option -TargetList $innerArgs -Name "--max-iters" -Value $diarizationMaxIters
            Add-Option -TargetList $innerArgs -Name "--method" -Value $diarizationMethod
            Add-Option -TargetList $innerArgs -Name "--min-cluster-size" -Value $diarizationMinClusterSize
            Add-Option -TargetList $innerArgs -Name "--seg-duration" -Value $diarizationSegDuration
            Add-Option -TargetList $innerArgs -Name "--segmentation-step" -Value $diarizationSegmentationStep
        }
        "rttm_to_json" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/rttm_to_json.py", "$($paths.diarization_rttm)", "$($paths.diarization_json)")
            if ($stabilizationEnabled) {
                Add-Option -TargetList $innerArgs -Name "--stabilized-output-json" -Value $stabilizedDiarizationJson
                Add-Option -TargetList $innerArgs -Name "--same-speaker-gap-sec" -Value $stabilizationSameSpeakerGapSec
                Add-Option -TargetList $innerArgs -Name "--bridge-max-sec" -Value $stabilizationBridgeMaxSec
                Add-Option -TargetList $innerArgs -Name "--bridge-gap-sec" -Value $stabilizationBridgeGapSec
                Add-Option -TargetList $innerArgs -Name "--tiny-segment-sec" -Value $stabilizationTinySegmentSec
                Add-Option -TargetList $innerArgs -Name "--absorb-gap-sec" -Value $stabilizationAbsorbGapSec
                Add-Option -TargetList $innerArgs -Name "--max-passes" -Value $stabilizationMaxPasses
            }
        }
        "merge_chunks" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/merge_speaker_chunks.py", "$diarizationJsonForMerge", "$($paths.speaker_chunks_json)", "--gap-threshold", "$gapThreshold", "--min-chunk-sec", "$minChunkSec", "--max-chunk-sec", "$maxChunkSec")
        }
        "cut_chunks" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/cut_chunks.py", "$chunkSource", "$($paths.speaker_chunks_json)", "--chunks-dir", "$($paths.chunks_dir)")
        }
        "extract_emotion" {
            $service = "speaker"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/extract_emotion.py", "$($paths.speaker_chunks_json)", "$($paths.emotion_json)", "--model-ref", $emotionModel, "--backend", $emotionBackend, "--device", $device)
            Add-Flag -TargetList $innerArgs -Name "--no-skip-existing" -Enabled (-not $emotionSkipExisting)
        }
        "run_asr" {
            $service = "speaker"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/run_asr.py", "$($paths.speaker_chunks_json)", "$($paths.asr_json)", "--model-dir", "$($models.asr)", "--device", $device, "--dtype", $dtype)
        }
        "translate" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/translate_chunks.py", "$($paths.asr_json)", "$($paths.translated_json)", "--mode", $translationMode, "--source-language", $sourceLanguage, "--target-language", $targetLanguage, "--env-file", $translationEnvFile, "--timeout-sec", "$timeoutSec")
            Add-Flag -TargetList $innerArgs -Name "--context-refine" -Enabled $translationContextRefine
            Add-Flag -TargetList $innerArgs -Name "--no-context-refine" -Enabled (-not $translationContextRefine)
            Add-Option -TargetList $innerArgs -Name "--context-batch-size" -Value $translationContextBatchSize
            Add-Flag -TargetList $innerArgs -Name "--duration-control" -Enabled $translationDurationControl
            Add-Flag -TargetList $innerArgs -Name "--no-duration-control" -Enabled (-not $translationDurationControl)
            Add-Option -TargetList $innerArgs -Name "--max-budget-rewrites" -Value $translationMaxBudgetRewrites
        }
        "build_timeline" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/build_master_timeline.py", "$($paths.speaker_chunks_json)", "$($paths.asr_json)", "$($paths.translated_json)", "$($paths.master_timeline_json)", "--dub-dir", "$($paths.dub_dir)")
            Add-Option -TargetList $innerArgs -Name "--emotion-json" -Value (Get-ObjectPropertyValue -Object $paths -Name "emotion_json")
            Add-Option -TargetList $innerArgs -Name "--dub-runtime-json-file" -Value $dubRuntimeProjectPath
        }
        "generate_tts_instructions" {
            if ($stylePriority -eq "voice") {
                $service = "controller"
                Add-Arguments -TargetList $innerArgs -Values @("python", "-c", "print('Skipping generate_tts_instructions because tts.style_priority=voice')")
            }
            else {
                $service = "controller"
                Add-Arguments -TargetList $innerArgs -Values @("python", "src/generate_tts_instructions.py", "$($paths.master_timeline_json)", "--mode", $ttsInstructionMode, "--env-file", $ttsInstructionEnvFile, "--timeout-sec", "$ttsInstructionTimeoutSec", "--batch-size", "$ttsInstructionBatchSize")
                Add-Flag -TargetList $innerArgs -Name "--no-skip-existing" -Enabled (-not $ttsInstructionSkipExisting)
                Add-Flag -TargetList $innerArgs -Name "--no-fallback-on-error" -Enabled (-not $ttsInstructionFallbackOnError)
                Add-Option -TargetList $innerArgs -Name "--style-priority" -Value $stylePriority
            }
        }
        "run_tts" {
            $service = $ttsService
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/run_tts.py", "$($paths.master_timeline_json)", "--engine", $ttsEngine, "--model-dir", "$($models.tts)", "--device", $device)
            Add-Option -TargetList $innerArgs -Name "--cosyvoice-repo" -Value (Get-ObjectPropertyValue -Object $models -Name "cosyvoice_repo")
            Add-Option -TargetList $innerArgs -Name "--system-prompt" -Value (Get-ObjectPropertyValue -Object $tts -Name "system_prompt")
            Add-Flag -TargetList $innerArgs -Name "--stream" -Enabled $stream
            Add-Flag -TargetList $innerArgs -Name "--no-skip-existing" -Enabled (-not $skipExisting)
            Add-Option -TargetList $innerArgs -Name "--min-prompt-sec" -Value $minPromptSec
            Add-Flag -TargetList $innerArgs -Name "--passthrough-source-audio" -Enabled $passthroughSourceAudio
            Add-Flag -TargetList $innerArgs -Name "--fit-to-duration" -Enabled $fitToDuration
            Add-Flag -TargetList $innerArgs -Name "--use-cross-lingual" -Enabled $useCrossLingual
            Add-Option -TargetList $innerArgs -Name "--target-language" -Value $targetLanguage
            Add-Option -TargetList $innerArgs -Name "--speed" -Value $ttsSpeed
            Add-Option -TargetList $innerArgs -Name "--reference-mode" -Value $referenceMode
            Add-Option -TargetList $innerArgs -Name "--duration-fit-min-tempo" -Value $durationFitMinTempo
            Add-Option -TargetList $innerArgs -Name "--duration-fit-max-tempo" -Value $durationFitMaxTempo
            Add-Flag -TargetList $innerArgs -Name "--duration-fit-trim-overlong" -Enabled $durationFitTrimOverlong
            Add-Flag -TargetList $innerArgs -Name "--trim-silence" -Enabled $trimSilence
            Add-Option -TargetList $innerArgs -Name "--silence-trim-threshold-dbfs" -Value $silenceTrimThresholdDbfs
            Add-Option -TargetList $innerArgs -Name "--max-leading-silence-sec" -Value $maxLeadingSilenceSec
            Add-Option -TargetList $innerArgs -Name "--max-trailing-silence-sec" -Value $maxTrailingSilenceSec
            Add-Flag -TargetList $innerArgs -Name "--no-cap-risky-self-reference" -Enabled (-not $capRiskySelfReference)
            Add-Option -TargetList $innerArgs -Name "--prompt-cap-max-sec" -Value $promptCapMaxSec
            Add-Flag -TargetList $innerArgs -Name "--compact-timeline" -Enabled $compactTimeline
            Add-Option -TargetList $innerArgs -Name "--style-priority" -Value $stylePriority
        }
        "validate_tts" {
            if (-not $ttsValidationEnabled) {
                $service = "controller"
                Add-Arguments -TargetList $innerArgs -Values @("python", "-c", "pass")
            }
            else {
                $service = "speaker"
                Add-Arguments -TargetList $innerArgs -Values @("python", "src/validate_tts_output.py", "$($paths.master_timeline_json)", $ttsValidationJson, "--model-dir", "$($models.asr)", "--device", $device, "--dtype", $dtype)
                Add-Option -TargetList $innerArgs -Name "--language" -Value $ttsValidationLanguage
                Add-Flag -TargetList $innerArgs -Name "--no-mark-stale-on-fail" -Enabled (-not $ttsValidationMarkStale)
                Add-Flag -TargetList $innerArgs -Name "--fail-on-error" -Enabled $ttsValidationFailOnError
            }
        }
        "compose_audio" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("python", "src/compose_audio.py", "$($paths.master_timeline_json)", "$($paths.final_dub_audio)", "--sample-rate", $finalSampleRate, "--channels", $finalChannels)
            Add-Option -TargetList $innerArgs -Name "--background-wav" -Value (Get-ObjectPropertyValue -Object $paths -Name "bgm_audio")
            Add-Option -TargetList $innerArgs -Name "--background-gain" -Value $backgroundGain
            Add-Option -TargetList $innerArgs -Name "--dub-gain" -Value $dubGain
            Add-Option -TargetList $innerArgs -Name "--target-peak-dbfs" -Value $targetPeakDbfs
        }
        "mux" {
            $service = "controller"
            Add-Arguments -TargetList $innerArgs -Values @("ffmpeg", "-y", "-i", (Get-ObjectPropertyValue -Object $configData -Name "input_video"), "-i", "$($paths.final_dub_audio)", "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0", "-c:a", $finalCodec, "-b:a", $finalBitrate, "-ar", $finalSampleRate, "-ac", $finalChannels, "$($paths.output_video)")
        }
        default {
            throw "Unsupported step: $step"
        }
    }

    $stepIndex++
    $logName = "{0:D2}_{1}.log" -f $stepIndex, $step
    $composeArgs = @($composeBase.ToArray()) + @("exec", "-T", $service) + @($innerArgs.ToArray())
    Invoke-Docker -Arguments $composeArgs -LogFile (Join-Path $logDir $logName) -Description "$step via $service"
}

Add-Content -Path $summaryLog -Value "Completed at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""
Write-Host "Pipeline completed."
Write-Host "Logs: $logDir"
Write-Host "Output video: $($paths.output_video)"
