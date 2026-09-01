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


function Assert-Dependency {
    param(
        [Parameter(Mandatory)]
        [string]$DumpbinOutput,

        [Parameter(Mandatory)]
        [string]$Dependency
    )

    if (
        $DumpbinOutput -notmatch
        [regex]::Escape($Dependency)
    ) {
        throw (
            "Required CTranslate2 dependency was not found: " +
            $Dependency
        )
    }

    Write-Success "dependency = $Dependency"
}


Write-Step "Validate CTranslate2 configuration"

& (
    Join-Path `
        $PSScriptRoot `
        "configure_ctranslate2.ps1"
) `
    -PythonPath $PythonPath `
    -ToolchainPath $ToolchainPath `
    -WorkspaceRoot $WorkspaceRoot


$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json

$ct2 = $toolchain.required.ctranslate2


$resolvedPython = Resolve-Path `
    -LiteralPath $PythonPath

$pythonScriptsPath = Split-Path `
    -Parent `
    $resolvedPython.Path

$cmakePath = Join-Path `
    $pythonScriptsPath `
    "cmake.exe"


$buildPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-build"

$installPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-install"


if (-not (Test-Path -LiteralPath $buildPath)) {
    throw (
        "CTranslate2 build directory not found: " +
        $buildPath
    )
}


Write-Step "Build CTranslate2"

& $cmakePath `
    --build $buildPath `
    --config Release

if ($LASTEXITCODE -ne 0) {
    throw "CTranslate2 native build failed."
}

Write-Success "CTranslate2 native build completed"


Write-Step "Install CTranslate2"

& $cmakePath `
    --install $buildPath `
    --config Release

if ($LASTEXITCODE -ne 0) {
    throw "CTranslate2 native installation failed."
}

Write-Success "CTranslate2 native installation completed"


Write-Step "Verify installed CTranslate2 library"

$ct2DllPath = Join-Path `
    $installPath `
    "bin\ctranslate2.dll"

if (-not (Test-Path -LiteralPath $ct2DllPath -PathType Leaf)) {
    throw (
        "Installed CTranslate2 DLL not found: " +
        $ct2DllPath
    )
}

Write-Success "ctranslate2.dll found"


$ct2Dll = Get-Item -LiteralPath $ct2DllPath

Write-Success (
    "ctranslate2.dll size = " +
    $ct2Dll.Length +
    " bytes"
)


$ct2Hash = (
    Get-FileHash `
        -LiteralPath $ct2DllPath `
        -Algorithm SHA256
).Hash

Write-Host "SHA256 ctranslate2.dll = $ct2Hash"


$referenceHash = [string](
    $toolchain.reference_artifacts.ctranslate2_dll_sha256
)

if ($ct2Hash -eq $referenceHash) {
    Write-Success (
        "CTranslate2 DLL matches the previously " +
        "validated reference artifact"
    )
}
else {
    Write-Warning (
        "CTranslate2 DLL does not byte-match the previous " +
        "reference artifact. This is recorded as provenance, " +
        "not a build failure."
    )

    Write-Host "Reference SHA256 = $referenceHash"
}


Write-Step "Inspect native dependencies"

$dumpbinOutput = (
    & dumpbin `
        /DEPENDENTS `
        $ct2DllPath `
        2>&1
) -join "`n"

if ($LASTEXITCODE -ne 0) {
    throw (
        "dumpbin failed while inspecting ctranslate2.dll.`n" +
        $dumpbinOutput
    )
}

Assert-Dependency `
    -DumpbinOutput $dumpbinOutput `
    -Dependency "hipblas.dll"

Assert-Dependency `
    -DumpbinOutput $dumpbinOutput `
    -Dependency "amdhip64_7.dll"

Assert-Dependency `
    -DumpbinOutput $dumpbinOutput `
    -Dependency "libiomp5md.dll"


$forbiddenDependencies = @(
    "cudart",
    "cublas",
    "cudnn"
)

foreach ($forbiddenDependency in $forbiddenDependencies) {
    if (
        $dumpbinOutput -match
        [regex]::Escape($forbiddenDependency)
    ) {
        throw (
            "Unexpected CUDA dependency found in " +
            "CTranslate2 DLL: " +
            $forbiddenDependency
        )
    }
}

Write-Success "no CUDA/cuDNN runtime dependencies detected"


Write-Host ""
Write-Host (
    "CTranslate2 native build validated successfully."
) -ForegroundColor Green

Write-Host ""
Write-Host "Build:   $buildPath"
Write-Host "Install: $installPath"
Write-Host "DLL:     $ct2DllPath"
Write-Host "SHA256:  $ct2Hash"