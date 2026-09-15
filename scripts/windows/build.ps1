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