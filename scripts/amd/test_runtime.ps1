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

    [int]$TimeoutSeconds = 180
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


function Assert-FileExists {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }

    Write-Success "$Description found"
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

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo

    $startInfo.FileName = $FilePath
    $startInfo.Arguments = ($ArgumentList -join " ")
    $startInfo.UseShellExecute = $false

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    try {
        $started = $process.Start()

        if (-not $started) {
            throw (
                "Failed to start process: " +
                $FilePath
            )
        }

        $exited = $process.WaitForExit(
            $TimeoutSeconds * 1000
        )

        if (-not $exited) {
            try {
                $process.Kill()
            }
            catch {
                # Preserve the original timeout failure.
            }

            $process.WaitForExit()

            throw (
                "Process did not exit within " +
                "$TimeoutSeconds seconds."
            )
        }

        # Complete asynchronous process bookkeeping before
        # reading ExitCode.
        $process.WaitForExit()

        return [int]$process.ExitCode
    }
    finally {
        $process.Dispose()
    }
}


$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json

$ct2 = $toolchain.required.ctranslate2

Assert-FileExists `
    -Path $RuntimeRequirementsPath `
    -Description "AMD runtime requirements"

Assert-FileExists `
    -Path $AudioFixturePath `
    -Description "real audio fixture"

$resolvedPython = Resolve-Path `
    -LiteralPath $PythonPath

$resolvedRequirements = Resolve-Path `
    -LiteralPath $RuntimeRequirementsPath

$resolvedAudioFixture = Resolve-Path `
    -LiteralPath $AudioFixturePath


$wheelPath = Join-Path `
    $WorkspaceRoot `
    (
        "wheel-dist\ctranslate2-" +
        $ct2.version +
        "-cp314-cp314-win_amd64.whl"
    )

$runtimeVenvPath = Join-Path `
    $WorkspaceRoot `
    "runtime-test-venv"

$runtimePythonPath = Join-Path `
    $runtimeVenvPath `
    "Scripts\python.exe"

$smokeTestPath = Join-Path `
    $PSScriptRoot `
    "runtime_smoke_test.py"


Assert-FileExists `
    -Path $wheelPath `
    -Description "script-produced CTranslate2 wheel"

Assert-FileExists `
    -Path $smokeTestPath `
    -Description "AMD runtime smoke test"


Write-Step "Create isolated AMD runtime environment"

if (Test-Path -LiteralPath $runtimeVenvPath) {
    Remove-Item `
        -LiteralPath $runtimeVenvPath `
        -Recurse `
        -Force
}

& uv venv `
    $runtimeVenvPath `
    --python $resolvedPython.Path

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create AMD runtime test environment."
}

Assert-FileExists `
    -Path $runtimePythonPath `
    -Description "runtime test Python"


Write-Step "Install pinned TheRock runtime"

$therockPackages = @()

foreach (
    $packageProperty in
    $toolchain.required.therock.packages.PSObject.Properties
) {
    $therockPackages += (
        $packageProperty.Name +
        "==" +
        [string]$packageProperty.Value
    )
}

& uv pip install `
    --python $runtimePythonPath `
    --index-url $toolchain.required.therock.package_index `
    @therockPackages

if ($LASTEXITCODE -ne 0) {
    throw "Failed to install pinned TheRock runtime."
}

Write-Success "TheRock runtime installed"


Write-Step "Install pinned Faster-Whisper runtime dependencies"

& uv pip install `
    --python $runtimePythonPath `
    --no-deps `
    -r $resolvedRequirements.Path

if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Faster-Whisper runtime dependencies."
}

Write-Success "Faster-Whisper runtime dependencies installed"


Write-Step "Install script-produced CTranslate2 wheel"

& uv pip install `
    --python $runtimePythonPath `
    --no-deps `
    $wheelPath

if ($LASTEXITCODE -ne 0) {
    throw "Failed to install custom CTranslate2 wheel."
}

Write-Success "custom CTranslate2 wheel installed"


Write-Step "Validate Python dependency graph"

& uv pip check `
    --python $runtimePythonPath

if ($LASTEXITCODE -ne 0) {
    throw "AMD runtime dependency validation failed."
}

Write-Success "Python dependency graph is consistent"


Write-Step "Run isolated GPU runtime smoke test"

$expectedCt2Hash = [string](
    $toolchain.reference_artifacts.scripted_rebuild_ctranslate2_dll_sha256
)

$expectedOpenMpHash = [string](
    $toolchain.required.intel_oneapi.artifacts.openmp_runtime.sha256
)


$arguments = @(
    "`"$smokeTestPath`"",
    "--audio-fixture",
    "`"$($resolvedAudioFixture.Path)`"",
    "--expected-ct2-version",
    "`"$($ct2.version)`"",
    "--expected-ct2-dll-sha256",
    "`"$expectedCt2Hash`"",
    "--expected-openmp-sha256",
    "`"$expectedOpenMpHash`""
)


$exitCode = Invoke-ProcessWithTimeout `
    -FilePath $runtimePythonPath `
    -ArgumentList $arguments `
    -TimeoutSeconds $TimeoutSeconds

if ($exitCode -ne 0) {
    throw (
        "AMD runtime smoke test failed with exit code " +
        $exitCode
    )
}

Write-Success "AMD runtime child process exited with code 0"


Write-Host ""
Write-Host (
    "Script-produced AMD runtime validated successfully."
) -ForegroundColor Green

Write-Host ""
Write-Host "Environment: $runtimeVenvPath"
Write-Host "Wheel:       $wheelPath"
Write-Host "Fixture:     $($resolvedAudioFixture.Path)"