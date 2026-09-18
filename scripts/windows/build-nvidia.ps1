[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


$repositoryRoot = (
    Resolve-Path `
        (Join-Path $PSScriptRoot "..\..")
).Path

$prepareRuntimeScript = Join-Path `
    $repositoryRoot `
    "scripts\nvidia\prepare-runtime.ps1"

$runtimeDirectory = Join-Path `
    $repositoryRoot `
    "build\nvidia-runtime"

$specPath = Join-Path `
    $repositoryRoot `
    "packaging\windows\AudioTranscriptionService-Nvidia.spec"

$distDirectory = Join-Path `
    $repositoryRoot `
    "dist\nvidia"

$workDirectory = Join-Path `
    $repositoryRoot `
    "build\pyinstaller-nvidia"

$outputPath = Join-Path `
    $distDirectory `
    "AudioTranscriptionService"

$executablePath = Join-Path `
    $outputPath `
    "AudioTranscriptionService.exe"

$runtimeManifestPath = Join-Path `
    $runtimeDirectory `
    "manifest.json"

$distributionMetadataPath = Join-Path `
    $repositoryRoot `
    "build\distribution-metadata\nvidia\distribution-metadata.json"


Write-Host ""
Write-Host "=== Prepare NVIDIA runtime ===" `
    -ForegroundColor Cyan

& $prepareRuntimeScript `
    -OutputDirectory $runtimeDirectory


Write-Host ""
Write-Host "=== Generate NVIDIA distribution metadata ===" `
    -ForegroundColor Cyan

Push-Location $repositoryRoot

try {
    uv run python -m scripts.generate_distribution_metadata `
        --profile nvidia `
        --project-root $repositoryRoot `
        --output $distributionMetadataPath `
        --nvidia-runtime-manifest $runtimeManifestPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "NVIDIA distribution metadata generation failed " +
            "with exit code $LASTEXITCODE"
        )
    }


    Write-Host ""
    Write-Host "=== Build NVIDIA Windows application ===" `
        -ForegroundColor Cyan

    uv run pyinstaller `
        --noconfirm `
        --clean `
        --distpath $distDirectory `
        --workpath $workDirectory `
        $specPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "NVIDIA PyInstaller build failed with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}


Write-Host ""
Write-Host "=== Build NVIDIA Windows application ===" `
    -ForegroundColor Cyan

Push-Location $repositoryRoot

try {
    uv run pyinstaller `
        --noconfirm `
        --clean `
        --distpath $distDirectory `
        --workpath $workDirectory `
        $specPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "NVIDIA PyInstaller build failed with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}


if (-not (
    Test-Path `
        -LiteralPath $executablePath `
        -PathType Leaf
)) {
    throw (
        "NVIDIA application executable was not produced: " +
        $executablePath
    )
}


$packagedRuntime = Join-Path `
    $outputPath `
    "_internal\nvidia-runtime"

$packagedDistributionMetadataPath = Join-Path `
    $outputPath `
    "_internal\distribution-metadata.json"

if (-not (
    Test-Path `
        -LiteralPath $packagedDistributionMetadataPath `
        -PathType Leaf
)) {
    throw (
        "Packaged NVIDIA distribution metadata was not found: " +
        $packagedDistributionMetadataPath
    )
}


$sourceMetadataHash = (
    Get-FileHash `
        -LiteralPath $distributionMetadataPath `
        -Algorithm SHA256
).Hash

$packagedMetadataHash = (
    Get-FileHash `
        -LiteralPath $packagedDistributionMetadataPath `
        -Algorithm SHA256
).Hash

if ($sourceMetadataHash -ne $packagedMetadataHash) {
    throw (
        "Packaged NVIDIA distribution metadata does not match " +
        "the generated build metadata"
    )
}


$toolchain = (
    Get-Content `
        -LiteralPath (
            Join-Path `
                $repositoryRoot `
                "scripts\nvidia\toolchain.json"
        ) `
        -Raw |
    ConvertFrom-Json
)

$expectedDlls = @(
    $toolchain.nvidia.required_dlls |
    Sort-Object
)

$packagedDlls = @(
    Get-ChildItem `
        -LiteralPath $packagedRuntime `
        -File `
        -Filter "*.dll" |
    Select-Object -ExpandProperty Name |
    Sort-Object
)

$missingDlls = @(
    $expectedDlls |
    Where-Object {
        $_ -notin $packagedDlls
    }
)

$unexpectedDlls = @(
    $packagedDlls |
    Where-Object {
        $_ -notin $expectedDlls
    }
)

if (
    $missingDlls.Count -gt 0 `
    -or $unexpectedDlls.Count -gt 0
) {
    throw (
        "Packaged NVIDIA runtime does not match the pinned contract. " +
        "missing=[$($missingDlls -join ', ')] " +
        "unexpected=[$($unexpectedDlls -join ', ')]"
    )
}


$applicationDirectory = Get-Item `
    -LiteralPath $outputPath

$sizeBytes = (
    Get-ChildItem `
        $applicationDirectory `
        -Recurse `
        -File |
    Measure-Object `
        -Property Length `
        -Sum
).Sum


Write-Host ""
Write-Host (
    "[OK] NVIDIA Windows application built"
) -ForegroundColor Green

Write-Host "Application: $outputPath"
Write-Host (
    "Size:        {0:N1} MB" -f (
        $sizeBytes / 1MB
    )
)
Write-Host (
    "NVIDIA DLLs: $($packagedDlls.Count)"
)