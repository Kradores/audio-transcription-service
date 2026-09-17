[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$OutputDirectory,

    [string]$ToolchainPath = (
        Join-Path `
            $PSScriptRoot `
            "toolchain.json"
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
    Write-Host "=== $Message ===" `
        -ForegroundColor Cyan
}


$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json

$workspace = Join-Path `
    $env:TEMP `
    "ats-nvidia-runtime-build"

$packagesDirectory = Join-Path `
    $workspace `
    "packages"


Write-Step "Prepare NVIDIA runtime workspace"

Remove-Item `
    $workspace `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    $OutputDirectory `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

New-Item `
    -ItemType Directory `
    -Path $packagesDirectory `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path $OutputDirectory `
    -Force |
    Out-Null


$packages = $toolchain.nvidia.packages

$packageSpecifications = @(
    (
        "nvidia-cublas-cu12==" +
        $packages.'nvidia-cublas-cu12'
    ),
    (
        "nvidia-cudnn-cu12==" +
        $packages.'nvidia-cudnn-cu12'
    ),
    (
        "nvidia-cuda-nvrtc-cu12==" +
        $packages.'nvidia-cuda-nvrtc-cu12'
    )
)


Write-Step "Install pinned NVIDIA packages"

& uv pip install `
    --target $packagesDirectory `
    --no-deps `
    @packageSpecifications

if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare NVIDIA runtime packages."
}


Write-Step "Stage NVIDIA DLLs"

$manifestFiles = @()

foreach ($dllName in $toolchain.nvidia.required_dlls) {
    $nameMatches = @(
        Get-ChildItem `
            $packagesDirectory `
            -Recurse `
            -File `
            -Filter $dllName
    )

    if ($nameMatches.Count -ne 1) {
        throw (
            "Expected exactly one NVIDIA DLL named " +
            "$dllName, found $($nameMatches.Count)"
        )
    }

    $destination = Join-Path `
        $OutputDirectory `
        $dllName

    Copy-Item `
        -LiteralPath $nameMatches[0].FullName `
        -Destination $destination

    $hash = (
        Get-FileHash `
            -LiteralPath $destination `
            -Algorithm SHA256
    ).Hash

    $manifestFiles += [ordered]@{
        name = $dllName
        sha256 = $hash
    }

    Write-Host "[OK] $dllName"
}


$manifest = [ordered]@{
    schema_version = 1

    generated_at_utc = (
        [DateTime]::UtcNow.ToString("o")
    )

    packages = [ordered]@{
        "nvidia-cublas-cu12" = (
            $packages.'nvidia-cublas-cu12'
        )
        "nvidia-cudnn-cu12" = (
            $packages.'nvidia-cudnn-cu12'
        )
        "nvidia-cuda-nvrtc-cu12" = (
            $packages.'nvidia-cuda-nvrtc-cu12'
        )
    }

    files = $manifestFiles
}


$manifestPath = Join-Path `
    $OutputDirectory `
    "manifest.json"

$manifestJson = (
    $manifest |
    ConvertTo-Json -Depth 6
)

$utf8WithoutBom = New-Object `
    System.Text.UTF8Encoding($false)

[System.IO.File]::WriteAllText(
    $manifestPath,
    $manifestJson,
    $utf8WithoutBom
)


Write-Host ""
Write-Host (
    "[OK] NVIDIA runtime prepared: " +
    $OutputDirectory
) -ForegroundColor Green