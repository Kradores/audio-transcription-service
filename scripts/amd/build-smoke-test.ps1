[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Write-Step {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host ""
    Write-Host "=== $Message ===" `
        -ForegroundColor Cyan
}


function Write-Success {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host "[OK] $Message" `
        -ForegroundColor Green
}


function Assert-File {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (
        Test-Path `
            -LiteralPath $Path `
            -PathType Leaf
    )) {
        throw "Required file not found: $Path"
    }
}


$repositoryRoot = (
    Resolve-Path `
        (Join-Path $PSScriptRoot "..\..")
).Path

$amdVenv = Join-Path `
    $repositoryRoot `
    ".venv-therock"

$amdPython = Join-Path `
    $amdVenv `
    "Scripts\python.exe"

$stageRuntimeScript = Join-Path `
    $PSScriptRoot `
    "stage_runtime.py"

$specPath = Join-Path `
    $repositoryRoot `
    "packaging\windows\AmdRuntimeSmokeTest.spec"

$toolchainPath = Join-Path `
    $PSScriptRoot `
    "toolchain.json"

$audioFixture = Join-Path `
    $repositoryRoot `
    "tests\fixtures\audio\english_speech.wav"

$workspace = Join-Path `
    $repositoryRoot `
    "build\amd-smoke"

$runtimeDirectory = Join-Path `
    $workspace `
    "runtime"

$pyinstallerWork = Join-Path `
    $workspace `
    "pyinstaller"

$distRoot = Join-Path `
    $repositoryRoot `
    "dist\amd-smoke"

$pyinstallerDist = Join-Path `
    $distRoot `
    "app"

$outputPath = Join-Path `
    $pyinstallerDist `
    "AmdRuntimeSmokeTest"

$executablePath = Join-Path `
    $outputPath `
    "AmdRuntimeSmokeTest.exe"

$packagedInternal = Join-Path `
    $outputPath `
    "_internal"

$packagedFixture = Join-Path `
    $packagedInternal `
    "fixtures\english_speech.wav"


Write-Step "Validate AMD smoke-test inputs"

Assert-File $amdPython
Assert-File $stageRuntimeScript
Assert-File $specPath
Assert-File $toolchainPath
Assert-File $audioFixture

$toolchain = Get-Content `
    -LiteralPath $toolchainPath `
    -Raw |
    ConvertFrom-Json

$expectedCt2Version = [string](
    $toolchain.required.ctranslate2.version
)

$expectedOpenMpHash = [string](
    $toolchain.required.intel_oneapi.artifacts.openmp_runtime.sha256
)

$sourceCt2Dll = Join-Path `
    $amdVenv `
    "Lib\site-packages\ctranslate2\ctranslate2.dll"

Assert-File $sourceCt2Dll

$expectedCt2Hash = (
    Get-FileHash `
        -LiteralPath $sourceCt2Dll `
        -Algorithm SHA256
).Hash

Write-Success (
    "CTranslate2 version = " +
    $expectedCt2Version
)

Write-Success (
    "CTranslate2 DLL SHA256 = " +
    $expectedCt2Hash
)


Write-Step "Prepare clean AMD smoke workspace"

Remove-Item `
    -LiteralPath $workspace `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    -LiteralPath $distRoot `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

New-Item `
    -ItemType Directory `
    -Path $workspace `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path $distRoot `
    -Force |
    Out-Null


Write-Step "Stage reduced AMD runtime"

Push-Location $repositoryRoot

try {
    & $amdPython `
        $stageRuntimeScript `
        --source-venv $amdVenv `
        --output $runtimeDirectory

    if ($LASTEXITCODE -ne 0) {
        throw (
            "AMD runtime staging failed with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}

Write-Success "Reduced AMD runtime staged"


Write-Step "Build AMD PyInstaller smoke executable"

Push-Location $repositoryRoot

try {
    & $amdPython `
        -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $pyinstallerDist `
        --workpath $pyinstallerWork `
        $specPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "AMD PyInstaller smoke build failed with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}


Assert-File $executablePath
Assert-File $packagedFixture

Write-Success "AMD PyInstaller smoke executable built"


Write-Step "Validate packaged AMD runtime layout"

$requiredPackagedFiles = @(
    (
        "_rocm_sdk_core\bin\amd_comgr.dll"
    ),
    (
        "_rocm_sdk_core\bin\amdhip64_7.dll"
    ),
    (
        "_rocm_sdk_libraries\bin\hipblas.dll"
    ),
    (
        "_rocm_sdk_libraries\bin\hiprand.dll"
    ),
    (
        "ctranslate2\ctranslate2.dll"
    ),
    (
        "ctranslate2\libiomp5md.dll"
    )
)

foreach ($relativePath in $requiredPackagedFiles) {
    Assert-File (
        Join-Path `
            $packagedInternal `
            $relativePath
    )
}

Write-Success "Required AMD runtime files are packaged"


Write-Step "Run packaged AMD smoke test"

$previousPythonPath = $env:PYTHONPATH
$previousVirtualEnv = $env:VIRTUAL_ENV
$previousTargetFamily = $env:ROCM_SDK_TARGET_FAMILY
$previousPreloadLibraries = (
    $env:ROCM_SDK_PRELOAD_LIBRARIES
)
$previousPath = $env:PATH

try {
    Remove-Item `
        Env:PYTHONPATH `
        -ErrorAction SilentlyContinue

    Remove-Item `
        Env:VIRTUAL_ENV `
        -ErrorAction SilentlyContinue

    Remove-Item `
        Env:ROCM_SDK_TARGET_FAMILY `
        -ErrorAction SilentlyContinue

    Remove-Item `
        Env:ROCM_SDK_PRELOAD_LIBRARIES `
        -ErrorAction SilentlyContinue

    $amdVenvNormalized = (
        [System.IO.Path]::GetFullPath(
            $amdVenv
        )
    ).TrimEnd("\")

    $cleanPathEntries = @(
        $previousPath -split ";" |
        Where-Object {
            if ([string]::IsNullOrWhiteSpace($_)) {
                return $false
            }

            $entry = $_

            try {
                $resolvedEntry = (
                    [System.IO.Path]::GetFullPath(
                        $entry
                    )
                ).TrimEnd("\")

                return -not (
                    $resolvedEntry.StartsWith(
                        $amdVenvNormalized,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
                )
            }
            catch {
                return $true
            }
        }
    )

    $env:PATH = (
        $cleanPathEntries -join ";"
    )

    $smokeArguments = @(
        "--audio-fixture",
        $packagedFixture,
        "--expected-ct2-version",
        $expectedCt2Version,
        "--expected-ct2-dll-sha256",
        $expectedCt2Hash,
        "--expected-openmp-sha256",
        $expectedOpenMpHash,
        "--expected-rocm-root",
        $packagedInternal
    )

    Push-Location $outputPath

    try {
        & $executablePath @smokeArguments

        $smokeExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($smokeExitCode -ne 0) {
        throw (
            "Packaged AMD smoke test failed with exit code " +
            $smokeExitCode
        )
    }
}
finally {
    $env:PATH = $previousPath

    if ($null -eq $previousPythonPath) {
        Remove-Item `
            Env:PYTHONPATH `
            -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }

    if ($null -eq $previousVirtualEnv) {
        Remove-Item `
            Env:VIRTUAL_ENV `
            -ErrorAction SilentlyContinue
    }
    else {
        $env:VIRTUAL_ENV = $previousVirtualEnv
    }

    if ($null -eq $previousTargetFamily) {
        Remove-Item `
            Env:ROCM_SDK_TARGET_FAMILY `
            -ErrorAction SilentlyContinue
    }
    else {
        $env:ROCM_SDK_TARGET_FAMILY = (
            $previousTargetFamily
        )
    }

    if ($null -eq $previousPreloadLibraries) {
        Remove-Item `
            Env:ROCM_SDK_PRELOAD_LIBRARIES `
            -ErrorAction SilentlyContinue
    }
    else {
        $env:ROCM_SDK_PRELOAD_LIBRARIES = (
            $previousPreloadLibraries
        )
    }
}

Write-Success (
    "Packaged AMD runtime completed real GPU inference"
)


$packageSizeBytes = (
    Get-ChildItem `
        -LiteralPath $outputPath `
        -Recurse `
        -File |
    Measure-Object `
        -Property Length `
        -Sum
).Sum


Write-Host ""
Write-Host (
    "AMD PyInstaller smoke test passed."
) -ForegroundColor Green

Write-Host ""
Write-Host "Executable: $executablePath"
Write-Host (
    "Package size: {0:N1} MB" -f (
        $packageSizeBytes / 1MB
    )
)