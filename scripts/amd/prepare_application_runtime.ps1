[CmdletBinding()]
param(
    [string]$PythonPath = ".venv-therock\Scripts\python.exe",

    [string]$ToolchainPath = (
        Join-Path $PSScriptRoot "toolchain.json"
    ),

    [string]$RuntimeRequirementsPath = (
        Join-Path $PSScriptRoot "runtime-requirements.txt"
    ),

    [string]$ApplicationRequirementsPath = (
        Join-Path `
            $PSScriptRoot `
            "application-runtime-requirements.txt"
    ),

    [string]$WorkspaceRoot = (
        Join-Path `
            $env:TEMP `
            "audio-transcription-service-amd"
    )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json


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


$runtimePythonPath = Join-Path `
    $WorkspaceRoot `
    "runtime-test-venv\Scripts\python.exe"


Write-Step "Prepare validated AMD transcription runtime"

& (
    Join-Path `
        $PSScriptRoot `
        "test_runtime.ps1"
) `
    -PythonPath $PythonPath `
    -ToolchainPath $ToolchainPath `
    -RuntimeRequirementsPath $RuntimeRequirementsPath `
    -WorkspaceRoot $WorkspaceRoot

if ($LASTEXITCODE -ne 0) {
    throw "AMD transcription runtime preparation failed."
}


Write-Step "Capture validated CTranslate2 artifact"

$runtimeCt2DllPath = Join-Path `
    $WorkspaceRoot `
    (
        "runtime-test-venv\Lib\site-packages\" +
        "ctranslate2\ctranslate2.dll"
    )

if (
    -not (
        Test-Path `
            -LiteralPath $runtimeCt2DllPath `
            -PathType Leaf
    )
) {
    throw (
        "Validated CTranslate2 DLL not found: " +
        $runtimeCt2DllPath
    )
}

$expectedCt2Hash = (
    Get-FileHash `
        -LiteralPath $runtimeCt2DllPath `
        -Algorithm SHA256
).Hash

Write-Success (
    "validated CTranslate2 DLL SHA256 = " +
    $expectedCt2Hash
)


Write-Step "Install application runtime dependencies"

& uv pip install `
    --python $runtimePythonPath `
    -r $ApplicationRequirementsPath

if ($LASTEXITCODE -ne 0) {
    throw "Application runtime dependency installation failed."
}


Write-Step "Validate dependency graph"

& uv pip check `
    --python $runtimePythonPath

if ($LASTEXITCODE -ne 0) {
    throw "Application runtime dependency graph is inconsistent."
}

Write-Success "application dependency graph is consistent"


Write-Step "Verify CTranslate2 artifact after application install"

if (
    -not (
        Test-Path `
            -LiteralPath $runtimeCt2DllPath `
            -PathType Leaf
    )
) {
    throw (
        "CTranslate2 DLL disappeared after application " +
        "dependency installation: " +
        $runtimeCt2DllPath
    )
}

$actualCt2Hash = (
    Get-FileHash `
        -LiteralPath $runtimeCt2DllPath `
        -Algorithm SHA256
).Hash

if ($actualCt2Hash -ne $expectedCt2Hash) {
    throw (
        "CTranslate2 DLL changed after application dependency " +
        "installation. " +
        "Expected='$expectedCt2Hash' " +
        "Actual='$actualCt2Hash'"
    )
}

Write-Success (
    "CTranslate2 DLL hash preserved after " +
    "application dependency installation"
)


Write-Step "Validate CPU Silero runtime"

@'
import torch
import torchaudio

print("torch_version =", torch.__version__)
print("torchaudio_version =", torchaudio.__version__)
print("torch_hip =", torch.version.hip)
print("torch_cuda =", torch.version.cuda)
print("gpu_available =", torch.cuda.is_available())

if "+cpu" not in torch.__version__:
    raise RuntimeError(
        f"Expected CPU PyTorch build, got {torch.__version__}"
    )

if "+cpu" not in torchaudio.__version__:
    raise RuntimeError(
        f"Expected CPU torchaudio build, got {torchaudio.__version__}"
    )

if torch.version.hip is not None:
    raise RuntimeError(
        f"Unexpected HIP-enabled PyTorch: {torch.version.hip}"
    )

if torch.version.cuda is not None:
    raise RuntimeError(
        f"Unexpected CUDA-enabled PyTorch: {torch.version.cuda}"
    )

if torch.cuda.is_available():
    raise RuntimeError(
        "CPU PyTorch unexpectedly reports GPU availability."
    )

print("CPU PyTorch runtime validated.")
'@ | & $runtimePythonPath -

if ($LASTEXITCODE -ne 0) {
    throw "CPU PyTorch runtime validation failed."
}

Write-Success "Silero/PyTorch CPU runtime validated"


Write-Step "Validate AMD transcription runtime after application install"

@'
import hashlib
from pathlib import Path

print("Initializing TheRock runtime...")

import rocm_sdk

rocm_sdk.initialize_process(
    preload_shortnames=[
        "amd_comgr",
        "amdhip64",
        "hipblas",
        "hiprand",
    ]
)

print("Importing CTranslate2...")

import ctranslate2

print("ctranslate2_version =", ctranslate2.__version__)
print("ctranslate2_path =", ctranslate2.__file__)

if ctranslate2.__version__ != "4.8.1":
    raise RuntimeError(
        f"Unexpected CTranslate2 version: {ctranslate2.__version__}"
    )

package_path = Path(ctranslate2.__file__).parent
dll_path = package_path / "ctranslate2.dll"

if not dll_path.is_file():
    raise RuntimeError(
        f"Packaged CTranslate2 DLL not found: {dll_path}"
    )

digest = hashlib.sha256(dll_path.read_bytes()).hexdigest().upper()

print("ctranslate2_dll_sha256 =", digest)
print("gpu_count =", ctranslate2.get_cuda_device_count())

if ctranslate2.get_cuda_device_count() < 1:
    raise RuntimeError(
        "CTranslate2 no longer sees the AMD GPU."
    )

compute_types = ctranslate2.get_supported_compute_types("cuda")

print(
    "supported_compute_types =",
    sorted(compute_types),
)

if "float16" not in compute_types:
    raise RuntimeError(
        "CTranslate2 no longer reports float16 support."
    )

print("AMD CTranslate2 runtime preserved.")
'@ | & $runtimePythonPath -

if ($LASTEXITCODE -ne 0) {
    throw (
        "AMD transcription runtime validation failed " +
        "after application dependency installation."
    )
}

Write-Success (
    "AMD CTranslate2 runtime preserved after " +
    "application dependency installation"
)


Write-Host ""
Write-Host (
    "Isolated AMD application runtime prepared successfully."
) -ForegroundColor Green

Write-Host ""
Write-Host "Python: $runtimePythonPath"