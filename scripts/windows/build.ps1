[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


$repositoryRoot = (
    Resolve-Path `
        (Join-Path $PSScriptRoot "..\..")
).Path

$specPath = Join-Path `
    $repositoryRoot `
    "packaging\windows\AudioTranscriptionService.spec"

$outputPath = Join-Path `
    $repositoryRoot `
    "dist\AudioTranscriptionService"

$distributionMetadataPath = Join-Path `
    $repositoryRoot `
    "build\distribution-metadata\cpu\distribution-metadata.json"

$executablePath = Join-Path `
    $outputPath `
    "AudioTranscriptionService.exe"


Write-Host ""
Write-Host "=== Build Windows application ===" `
    -ForegroundColor Cyan

Write-Host "Repository: $repositoryRoot"
Write-Host "Spec:       $specPath"


Push-Location $repositoryRoot

try {
    Write-Host ""
    Write-Host "=== Generate CPU distribution metadata ===" `
        -ForegroundColor Cyan

    uv run python -m scripts.generate_distribution_metadata `
        --profile cpu `
        --project-root $repositoryRoot `
        --output $distributionMetadataPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "CPU distribution metadata generation failed " +
            "with exit code $LASTEXITCODE"
        )
    }


    uv run pyinstaller `
        --noconfirm `
        --clean `
        $specPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "PyInstaller failed with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}


if (-not (Test-Path -LiteralPath $executablePath)) {
    throw (
        "PyInstaller completed but the expected " +
        "executable was not found: $executablePath"
    )
}


$packagedDistributionMetadataPath = Join-Path `
    $outputPath `
    "_internal\distribution-metadata.json"

if (-not (
    Test-Path `
        -LiteralPath $packagedDistributionMetadataPath `
        -PathType Leaf
)) {
    throw (
        "Packaged CPU distribution metadata was not found: " +
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
        "Packaged CPU distribution metadata does not match " +
        "the generated build metadata"
    )
}


$bytes = (
    Get-ChildItem `
        -LiteralPath $outputPath `
        -Recurse `
        -File |
    Measure-Object `
        -Property Length `
        -Sum
).Sum


$sizeMb = $bytes / 1MB


Write-Host ""
Write-Host "[OK] Windows application built" `
    -ForegroundColor Green

Write-Host "Executable: $executablePath"
Write-Host (
    "Package size: {0:N1} MB" -f $sizeMb
)