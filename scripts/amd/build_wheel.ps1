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
    )
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


Write-Step "Validate native CTranslate2 build"

& (
    Join-Path `
        $PSScriptRoot `
        "build_ctranslate2.ps1"
) `
    -PythonPath $PythonPath `
    -ToolchainPath $ToolchainPath `
    -WorkspaceRoot $WorkspaceRoot

if ($LASTEXITCODE -ne 0) {
    throw "Native CTranslate2 build validation failed."
}


$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json

$ct2 = $toolchain.required.ctranslate2

$resolvedPython = Resolve-Path `
    -LiteralPath $PythonPath


$sourcePath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)"

$installPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-install"

$openMpStagePath = Join-Path `
    $WorkspaceRoot `
    (
        "intel-openmp-" +
        $toolchain.required.intel_oneapi.version
    )

$wheelSourcePath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-python-wheel"

$wheelVenvPath = Join-Path `
    $WorkspaceRoot `
    "wheel-build-venv"

$wheelDistPath = Join-Path `
    $WorkspaceRoot `
    "wheel-dist"


$nativeDllPath = Join-Path `
    $installPath `
    "bin\ctranslate2.dll"

$nativeImportLibraryPath = Join-Path `
    $installPath `
    "lib\ctranslate2.lib"

$openMpRuntimePath = Join-Path `
    $openMpStagePath `
    "bin\libiomp5md.dll"


Assert-FileExists `
    -Path $nativeDllPath `
    -Description "native ctranslate2.dll"

Assert-FileExists `
    -Path $nativeImportLibraryPath `
    -Description "native ctranslate2.lib"

Assert-FileExists `
    -Path $openMpRuntimePath `
    -Description "staged libiomp5md.dll"


Write-Step "Verify packaged Intel OpenMP runtime"

$openMpHash = (
    Get-FileHash `
        -LiteralPath $openMpRuntimePath `
        -Algorithm SHA256
).Hash

$expectedOpenMpHash = [string](
    $toolchain.required.intel_oneapi.artifacts.openmp_runtime.sha256
)

if ($openMpHash -ne $expectedOpenMpHash) {
    throw (
        "Staged libiomp5md.dll hash mismatch. " +
        "Expected='$expectedOpenMpHash' " +
        "Actual='$openMpHash'"
    )
}

Write-Success "libiomp5md.dll hash verified"


Write-Step "Prepare isolated Python wheel source"

foreach ($path in @(
    $wheelSourcePath,
    $wheelVenvPath,
    $wheelDistPath
)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item `
            -LiteralPath $path `
            -Recurse `
            -Force
    }
}

New-Item `
    -ItemType Directory `
    -Path @(
        $wheelSourcePath,
        $wheelDistPath
    ) `
    -Force |
    Out-Null


$pythonSourcePath = Join-Path `
    $sourcePath `
    "python"

Copy-Item `
    -Path (
        Join-Path $pythonSourcePath "*"
    ) `
    -Destination $wheelSourcePath `
    -Recurse `
    -Force


$packagePath = Join-Path `
    $wheelSourcePath `
    "ctranslate2"

if (-not (Test-Path -LiteralPath $packagePath -PathType Container)) {
    throw (
        "CTranslate2 Python package was not copied: " +
        $packagePath
    )
}


Copy-Item `
    -LiteralPath $nativeDllPath `
    -Destination (
        Join-Path $packagePath "ctranslate2.dll"
    ) `
    -Force

Copy-Item `
    -LiteralPath $openMpRuntimePath `
    -Destination (
        Join-Path $packagePath "libiomp5md.dll"
    ) `
    -Force

Write-Success "native runtime DLLs staged into Python package"


Write-Step "Create isolated wheel build environment"

& uv venv `
    $wheelVenvPath `
    --python $resolvedPython.Path

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create wheel build environment."
}


$wheelPythonPath = Join-Path `
    $wheelVenvPath `
    "Scripts\python.exe"

Assert-FileExists `
    -Path $wheelPythonPath `
    -Description "wheel build Python"


$wheelBuild = $toolchain.required.python_wheel_build

& uv pip install `
    --python $wheelPythonPath `
    (
        "pybind11==" +
        $wheelBuild.pybind11
    ) `
    (
        "setuptools==" +
        $wheelBuild.setuptools
    ) `
    (
        "wheel==" +
        $wheelBuild.wheel
    )

if ($LASTEXITCODE -ne 0) {
    throw "Failed to install wheel build dependencies."
}

Write-Success "wheel build dependencies installed"


Write-Step "Validate Python wheel build toolchain"

@'
import importlib.metadata
from pathlib import Path

import pybind11
import setuptools
import wheel

if setuptools.__file__ is None:
    raise RuntimeError(
        "setuptools resolved as a namespace package instead "
        "of a real installation."
    )

from distutils._msvccompiler import MSVCCompiler

print(
    "pybind11_version =",
    importlib.metadata.version("pybind11"),
)
print(
    "setuptools_version =",
    importlib.metadata.version("setuptools"),
)
print(
    "setuptools_path =",
    Path(setuptools.__file__).resolve(),
)
print(
    "wheel_version =",
    importlib.metadata.version("wheel"),
)
print(
    "msvc_compiler =",
    MSVCCompiler.__module__,
)

print("Python wheel build toolchain validated.")
'@ | & $wheelPythonPath -

if ($LASTEXITCODE -ne 0) {
    throw "Python wheel build toolchain validation failed."
}

Write-Success "Python wheel build toolchain validated"


foreach ($commandName in @(
    "cl",
    "link",
    "lib"
)) {
    if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw (
            "MSVC command is unavailable before wheel build: " +
            $commandName
        )
    }
}

Write-Success "existing MSVC environment ready for Python extension build"


Write-Step "Build CTranslate2 Python wheel"

# File: scripts/amd/build_wheel.ps1

$previousCTranslate2Root = $env:CTRANSLATE2_ROOT
$previousDistutilsUseSdk = $env:DISTUTILS_USE_SDK
$previousMsSdk = $env:MSSdk

try {
    $env:CTRANSLATE2_ROOT = $installPath

    # test_prerequisites.ps1 already initialized and validated the
    # Visual Studio C++ environment in this PowerShell process.
    #
    # Tell setuptools/distutils to reuse it instead of invoking
    # vcvarsall.bat again.
    $env:DISTUTILS_USE_SDK = "1"
    $env:MSSdk = "1"

    Push-Location $wheelSourcePath

    try {
        & $wheelPythonPath `
            setup.py `
            bdist_wheel `
            --dist-dir $wheelDistPath

        if ($LASTEXITCODE -ne 0) {
            throw "CTranslate2 Python wheel build failed."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:CTRANSLATE2_ROOT = $previousCTranslate2Root
    $env:DISTUTILS_USE_SDK = $previousDistutilsUseSdk
    $env:MSSdk = $previousMsSdk
}


Write-Step "Verify wheel contents"

$wheels = @(
    Get-ChildItem `
        -LiteralPath $wheelDistPath `
        -Filter "*.whl" `
        -File
)

if ($wheels.Count -ne 1) {
    throw (
        "Expected exactly one wheel, found " +
        $wheels.Count
    )
}

$wheel = $wheels[0]

$expectedWheelNamePattern = (
    "^ctranslate2-" +
    [regex]::Escape($ct2.version) +
    "-cp314-cp314-win_amd64\.whl$"
)

if ($wheel.Name -notmatch $expectedWheelNamePattern) {
    throw (
        "Unexpected wheel filename: " +
        $wheel.Name
    )
}


$wheelEntries = @(
    & $wheelPythonPath -c @"
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as wheel:
    for name in wheel.namelist():
        print(name)
"@ $wheel.FullName
)

if ($LASTEXITCODE -ne 0) {
    throw "Failed to inspect generated wheel."
}


$requiredPatterns = @(
    "^ctranslate2/_ext.*\.pyd$",
    "^ctranslate2/ctranslate2\.dll$",
    "^ctranslate2/libiomp5md\.dll$"
)

foreach ($pattern in $requiredPatterns) {
    $matchingEntry = $wheelEntries |
        Where-Object {
            $_ -match $pattern
        } |
        Select-Object -First 1

    if ($null -eq $matchingEntry) {
        throw (
            "Required wheel entry was not found: " +
            $pattern
        )
    }

    Write-Success "wheel contains $matchingEntry"
}


$wheelHash = (
    Get-FileHash `
        -LiteralPath $wheel.FullName `
        -Algorithm SHA256
).Hash


Write-Host ""
Write-Host (
    "CTranslate2 AMD Python wheel built successfully."
) -ForegroundColor Green

Write-Host ""
Write-Host "Wheel:  $($wheel.FullName)"
Write-Host "Size:   $($wheel.Length) bytes"
Write-Host "SHA256: $wheelHash"