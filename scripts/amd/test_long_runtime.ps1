[CmdletBinding()]
param(
    [string]$PythonPath = ".venv-therock\Scripts\python.exe",

    [string]$ToolchainPath = (
        Join-Path $PSScriptRoot "toolchain.json"
    ),

    [string]$RuntimeRequirementsPath = (
        Join-Path $PSScriptRoot "runtime-requirements.txt"
    ),

    [string]$WorkspaceRoot = (
        Join-Path `
            $env:TEMP `
            "audio-transcription-service-amd"
    ),

    [string]$AudioFixturePath = (
        Join-Path `
            (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) `
            "tests\fixtures\audio\english_speech.wav"
    ),

    [int]$DurationMinutes = 20,

    [int]$TeardownTimeoutSeconds = 120
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


function Invoke-ProcessWithTimeout {
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,

        [Parameter(Mandatory)]
        [string[]]$ArgumentList,

        [Parameter(Mandatory)]
        [int]$TimeoutSeconds
    )

    $startInfo = New-Object `
        System.Diagnostics.ProcessStartInfo

    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (
        $ArgumentList -join " "
    )
    $startInfo.UseShellExecute = $false

    $process = New-Object `
        System.Diagnostics.Process

    $process.StartInfo = $startInfo

    try {
        if (-not $process.Start()) {
            throw "Failed to start process: $FilePath"
        }

        $exited = $process.WaitForExit(
            $TimeoutSeconds * 1000
        )

        if (-not $exited) {
            try {
                $process.Kill()
            }
            catch {
                # Preserve timeout failure.
            }

            $process.WaitForExit()

            throw (
                "Long-running AMD runtime process did not " +
                "exit within $TimeoutSeconds seconds."
            )
        }

        $process.WaitForExit()

        return [int]$process.ExitCode
    }
    finally {
        $process.Dispose()
    }
}


if ($DurationMinutes -le 0) {
    throw "DurationMinutes must be greater than zero."
}


Write-Step "Prepare validated isolated AMD runtime"

& (
    Join-Path `
        $PSScriptRoot `
        "test_runtime.ps1"
) `
    -PythonPath $PythonPath `
    -ToolchainPath $ToolchainPath `
    -RuntimeRequirementsPath $RuntimeRequirementsPath `
    -WorkspaceRoot $WorkspaceRoot `
    -AudioFixturePath $AudioFixturePath

if ($LASTEXITCODE -ne 0) {
    throw (
        "AMD runtime smoke-test preparation failed."
    )
}


$runtimePythonPath = Join-Path `
    $WorkspaceRoot `
    "runtime-test-venv\Scripts\python.exe"

$longTestPath = Join-Path `
    $PSScriptRoot `
    "runtime_long_test.py"

$resolvedAudioFixture = Resolve-Path `
    -LiteralPath $AudioFixturePath


if (
    -not (
        Test-Path `
            -LiteralPath $runtimePythonPath `
            -PathType Leaf
    )
) {
    throw (
        "Runtime test Python not found: " +
        $runtimePythonPath
    )
}

if (
    -not (
        Test-Path `
            -LiteralPath $longTestPath `
            -PathType Leaf
    )
) {
    throw (
        "Long-running runtime test not found: " +
        $longTestPath
    )
}


$durationSeconds = $DurationMinutes * 60

# The child gets the requested workload duration plus a
# separate teardown/startup allowance.
$processTimeoutSeconds = (
    $durationSeconds +
    $TeardownTimeoutSeconds
)


Write-Step (
    "Run AMD long-running teardown regression " +
    "($DurationMinutes minutes)"
)


$arguments = @(
    "`"$longTestPath`"",
    "--audio-fixture",
    "`"$($resolvedAudioFixture.Path)`"",
    "--duration-seconds",
    "$durationSeconds"
)


$exitCode = Invoke-ProcessWithTimeout `
    -FilePath $runtimePythonPath `
    -ArgumentList $arguments `
    -TimeoutSeconds $processTimeoutSeconds


if ($exitCode -ne 0) {
    throw (
        "AMD long-running teardown regression " +
        "failed with exit code $exitCode"
    )
}


Write-Success (
    "AMD long-running child process exited " +
    "with code 0"
)

Write-Host ""
Write-Host (
    "AMD long-running teardown regression " +
    "validated successfully."
) -ForegroundColor Green