# File: scripts/amd/prepare.ps1

[CmdletBinding()]
param(
    [switch]$Clean,

    [switch]$RunLongValidation,

    [ValidateRange(1, 1440)]
    [int]$LongValidationMinutes = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Write-Step {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}


function Write-Success {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host "[OK] $Message" -ForegroundColor Green
}


function Invoke-AmdScript {
    param(
        [Parameter(Mandatory)]
        [string]$Description,

        [Parameter(Mandatory)]
        [string]$ScriptName,

        [string[]]$Arguments = @()
    )

    $scriptPath = Join-Path `
        $PSScriptRoot `
        $ScriptName

    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw (
            "Required AMD script not found: " +
            $scriptPath
        )
    }

    Write-Step $Description

    & $scriptPath @Arguments

    if (-not $?) {
        throw (
            "AMD preparation step failed: " +
            $Description
        )
    }

    Write-Success $Description
}


Write-Host ""
Write-Host (
    "AMD / TheRock transcription environment preparation"
) -ForegroundColor Green

Write-Host ""
Write-Host (
    "This is the primary entry point for the AMD setup."
)


Invoke-AmdScript `
    -Description "Validate AMD build prerequisites" `
    -ScriptName "test_prerequisites.ps1"


$prepareArguments = @()

if ($Clean) {
    $prepareArguments += "-Clean"
}


Invoke-AmdScript `
    -Description "Prepare pinned CTranslate2 source and build workspace" `
    -ScriptName "prepare_ctranslate2_build.ps1" `
    -Arguments $prepareArguments


# build_ctranslate2.ps1 owns the validated configure + native-build path.
Invoke-AmdScript `
    -Description "Build and validate CTranslate2 native library" `
    -ScriptName "build_ctranslate2.ps1"


Invoke-AmdScript `
    -Description "Build and validate custom CTranslate2 wheel" `
    -ScriptName "build_wheel.ps1"


if ($RunLongValidation) {
    Invoke-AmdScript `
        -Description (
            "Run sustained AMD teardown validation " +
            "($LongValidationMinutes minutes)"
        ) `
        -ScriptName "test_long_runtime.ps1" `
        -Arguments @(
            "-DurationMinutes",
            "$LongValidationMinutes"
        )
}


# Keep this last.
#
# test_long_runtime.ps1 prepares its own isolated Faster-Whisper runtime.
# prepare_application_runtime.ps1 recreates the final isolated environment
# and leaves it ready to run the complete application.
Invoke-AmdScript `
    -Description "Prepare and validate complete AMD application runtime" `
    -ScriptName "prepare_application_runtime.ps1"


$runtimePythonPath = Join-Path `
    $env:TEMP `
    (
        "audio-transcription-service-amd\" +
        "runtime-test-venv\Scripts\python.exe"
    )


Write-Host ""
Write-Host (
    "AMD application runtime prepared successfully."
) -ForegroundColor Green

Write-Host ""
Write-Host "Runtime Python:"
Write-Host "  $runtimePythonPath"

Write-Host ""
Write-Host "Run the application with:"
Write-Host (
    "  & `"$runtimePythonPath`" -m app"
)

Write-Host ""
Write-Host (
    "For a clean native rebuild, run:"
)
Write-Host (
    "  .\scripts\amd\prepare.ps1 -Clean"
)

Write-Host ""
Write-Host (
    "For the full sustained teardown validation, run:"
)
Write-Host (
    "  .\scripts\amd\prepare.ps1 " +
    "-RunLongValidation"
)