[CmdletBinding()]
param(
    [string]$PythonPath = ".venv-therock\Scripts\python.exe",

    [string]$ToolchainPath = (
        Join-Path $PSScriptRoot "toolchain.json"
    ),

    [string]$WorkspaceRoot = (
        Join-Path `
            $env:TEMP `
            "audio-transcription-service-amd"
    ),

    [switch]$Clean
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


function Assert-CommandExists {
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    if ($null -eq (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}


Write-Step "Validate build prerequisites"

& (
    Join-Path `
        $PSScriptRoot `
        "test_prerequisites.ps1"
) `
    -PythonPath $PythonPath `
    -ToolchainPath $ToolchainPath

if ($LASTEXITCODE -ne 0) {
    throw "AMD build prerequisite validation failed."
}


Assert-CommandExists "git"

$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json

$ct2 = $toolchain.required.ctranslate2


$sourcePath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)"

$buildPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-build"

$installPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-install"

$openMpStagePath = Join-Path `
    $WorkspaceRoot `
    "intel-openmp-$($toolchain.required.intel_oneapi.version)"


if ($Clean -and (Test-Path -LiteralPath $WorkspaceRoot)) {
    Write-Step "Clean previous workspace"

    Remove-Item `
        -LiteralPath $WorkspaceRoot `
        -Recurse `
        -Force

    Write-Success "Previous workspace removed"
}


New-Item `
    -ItemType Directory `
    -Path $WorkspaceRoot `
    -Force |
    Out-Null


Write-Step "Prepare CTranslate2 source"


if (-not (Test-Path -LiteralPath $sourcePath)) {
    git clone `
        --recursive `
        $ct2.source_repository `
        $sourcePath

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone CTranslate2."
    }
}
else {
    Write-Success "Existing CTranslate2 repository found"
}


Push-Location $sourcePath

try {
    git fetch `
        --tags `
        --force

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to fetch CTranslate2 tags."
    }

    git checkout `
        --detach `
        $ct2.source_tag

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Failed to checkout CTranslate2 tag " +
            $ct2.source_tag
        )
    }

    git submodule update `
        --init `
        --recursive

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to initialize CTranslate2 submodules."
    }

    $actualCommit = (
        git rev-parse HEAD
    ).Trim()

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to read CTranslate2 revision."
    }

    if (
        -not $actualCommit.StartsWith(
            $ct2.source_commit,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw (
            "CTranslate2 revision mismatch. " +
            "Expected='$($ct2.source_commit)' " +
            "Actual='$actualCommit'"
        )
    }

    $status = @(
        git status `
            --porcelain `
            --untracked-files=no
    )

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect CTranslate2 source status."
    }

    if ($status.Count -ne 0) {
        throw (
            "CTranslate2 source tree contains tracked modifications:`n" +
            ($status -join "`n")
        )
    }

    Write-Success (
        "CTranslate2 source revision = " +
        $actualCommit
    )
}
finally {
    Pop-Location
}


Write-Step "Prepare Intel OpenMP staging directory"


$programFilesX86 = [Environment]::GetFolderPath(
    [Environment+SpecialFolder]::ProgramFilesX86
)

$oneApiRoot = Join-Path `
    $programFilesX86 `
    (
        "Intel\oneAPI\compiler\" +
        $toolchain.required.intel_oneapi.version
    )

$openMpIncludePath = Join-Path `
    $openMpStagePath `
    "include"

$openMpLibPath = Join-Path `
    $openMpStagePath `
    "lib"

$openMpBinPath = Join-Path `
    $openMpStagePath `
    "bin"

New-Item `
    -ItemType Directory `
    -Path @(
        $openMpIncludePath,
        $openMpLibPath,
        $openMpBinPath
    ) `
    -Force |
    Out-Null


$headerSource = Join-Path `
    $oneApiRoot `
    $toolchain.required.intel_oneapi.artifacts.openmp_header.relative_path

$librarySource = Join-Path `
    $oneApiRoot `
    $toolchain.required.intel_oneapi.artifacts.openmp_import_library.relative_path

$runtimeSource = Join-Path `
    $oneApiRoot `
    $toolchain.required.intel_oneapi.artifacts.openmp_runtime.relative_path


Copy-Item `
    -LiteralPath $headerSource `
    -Destination (
        Join-Path $openMpIncludePath "omp.h"
    ) `
    -Force

Copy-Item `
    -LiteralPath $librarySource `
    -Destination (
        Join-Path $openMpLibPath "libiomp5md.lib"
    ) `
    -Force

Copy-Item `
    -LiteralPath $runtimeSource `
    -Destination (
        Join-Path $openMpBinPath "libiomp5md.dll"
    ) `
    -Force


$stagedLibraryHash = (
    Get-FileHash `
        -LiteralPath (
            Join-Path `
                $openMpLibPath `
                "libiomp5md.lib"
        ) `
        -Algorithm SHA256
).Hash

$stagedRuntimeHash = (
    Get-FileHash `
        -LiteralPath (
            Join-Path `
                $openMpBinPath `
                "libiomp5md.dll"
        ) `
        -Algorithm SHA256
).Hash


if (
    $stagedLibraryHash -ne
    $toolchain.required.intel_oneapi.artifacts.openmp_import_library.sha256
) {
    throw "Staged Intel OpenMP import library hash mismatch."
}

if (
    $stagedRuntimeHash -ne
    $toolchain.required.intel_oneapi.artifacts.openmp_runtime.sha256
) {
    throw "Staged Intel OpenMP runtime hash mismatch."
}

Write-Success "Intel OpenMP artifacts staged and verified"


Write-Step "Prepare native output directories"


New-Item `
    -ItemType Directory `
    -Path @(
        $buildPath,
        $installPath
    ) `
    -Force |
    Out-Null


Write-Host ""
Write-Host "CTranslate2 build workspace prepared successfully." `
    -ForegroundColor Green

Write-Host ""
Write-Host "Source:       $sourcePath"
Write-Host "Build:        $buildPath"
Write-Host "Install:      $installPath"
Write-Host "OpenMP stage: $openMpStagePath"
Write-Host "Architecture: $($ct2.hip_architecture)"
Write-Host "OpenMP:       $($ct2.openmp_runtime)"