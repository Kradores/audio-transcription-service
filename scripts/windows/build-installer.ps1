[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Find-InnoSetupCompiler {
    if ($env:INNO_SETUP_COMPILER) {
        if (-not (Test-Path -LiteralPath $env:INNO_SETUP_COMPILER)) {
            throw (
                "INNO_SETUP_COMPILER points to a missing file: " +
                $env:INNO_SETUP_COMPILER
            )
        }

        return (
            Resolve-Path -LiteralPath $env:INNO_SETUP_COMPILER
        ).Path
    }

    $command = Get-Command `
        "ISCC.exe" `
        -ErrorAction SilentlyContinue

    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @()

    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path `
            $env:LOCALAPPDATA `
            "Programs\Inno Setup 7\ISCC.exe"

        $candidates += Join-Path `
            $env:LOCALAPPDATA `
            "Programs\Inno Setup 6\ISCC.exe"
    }

    if (${env:ProgramFiles(x86)}) {
        $candidates += Join-Path `
            ${env:ProgramFiles(x86)} `
            "Inno Setup 7\ISCC.exe"

        $candidates += Join-Path `
            ${env:ProgramFiles(x86)} `
            "Inno Setup 6\ISCC.exe"
    }

    if ($env:ProgramFiles) {
        $candidates += Join-Path `
            $env:ProgramFiles `
            "Inno Setup 7\ISCC.exe"

        $candidates += Join-Path `
            $env:ProgramFiles `
            "Inno Setup 6\ISCC.exe"
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (
                Resolve-Path -LiteralPath $candidate
            ).Path
        }
    }

    throw @"
Inno Setup compiler ISCC.exe was not found.

Install Inno Setup, for example:

    winget install --id JRSoftware.InnoSetup --exact --scope user

Or set INNO_SETUP_COMPILER to the full path of ISCC.exe.
"@
}


$repositoryRoot = (
    Resolve-Path `
        (Join-Path $PSScriptRoot "..\..")
).Path

$applicationBuildScript = Join-Path `
    $repositoryRoot `
    "scripts\windows\build.ps1"

$installerScript = Join-Path `
    $repositoryRoot `
    "packaging\windows\AudioTranscriptionService.iss"

$applicationDist = Join-Path `
    $repositoryRoot `
    "dist\AudioTranscriptionService"

$applicationExecutable = Join-Path `
    $applicationDist `
    "AudioTranscriptionService.exe"

$installerOutputDirectory = Join-Path `
    $repositoryRoot `
    "dist\installer"

$defaultConfigSource = Join-Path `
    $repositoryRoot `
    "config\config.example.yaml"


Write-Host ""
Write-Host "=== Build Windows installer ===" `
    -ForegroundColor Cyan

Write-Host "Repository: $repositoryRoot"


Write-Host ""
Write-Host "=== Build packaged application ===" `
    -ForegroundColor Cyan

& $applicationBuildScript

if ($LASTEXITCODE -ne 0) {
    throw (
        "Application build failed with exit code " +
        $LASTEXITCODE
    )
}

if (-not (Test-Path -LiteralPath $applicationExecutable)) {
    throw (
        "Expected packaged executable was not found: " +
        $applicationExecutable
    )
}


Push-Location $repositoryRoot

try {
    $versionScript = @'
import pathlib
import tomllib

document = tomllib.loads(
    pathlib.Path("pyproject.toml").read_text(
        encoding="utf-8",
    )
)

print(document["project"]["version"])
'@

    $versionOutput = $versionScript |
        uv run python -

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Could not read application version from pyproject.toml"
        )
    }
}
finally {
    Pop-Location
}


$appVersion = (
    $versionOutput |
    Out-String
).Trim()

if ([string]::IsNullOrWhiteSpace($appVersion)) {
    throw "Application version is empty"
}


if (-not (Test-Path -LiteralPath $defaultConfigSource)) {
    throw (
        "Default Windows configuration was not found: " +
        $defaultConfigSource
    )
}


$innoSetupCompiler = Find-InnoSetupCompiler


New-Item `
    -ItemType Directory `
    -Path $installerOutputDirectory `
    -Force |
    Out-Null


Write-Host ""
Write-Host "=== Compile installer ===" `
    -ForegroundColor Cyan

Write-Host "Application version: $appVersion"
Write-Host "Inno Setup compiler: $innoSetupCompiler"


& $innoSetupCompiler `
    "-dAppVersion=$appVersion" `
    "-dAppSourceDir=$applicationDist" `
    "-dDefaultConfigSource=$defaultConfigSource" `
    "-dInstallerOutputDir=$installerOutputDirectory" `
    $installerScript

if ($LASTEXITCODE -ne 0) {
    throw (
        "Inno Setup failed with exit code " +
        $LASTEXITCODE
    )
}


$installerPath = Join-Path `
    $installerOutputDirectory `
    "AudioTranscriptionService-Setup-$appVersion.exe"

if (-not (Test-Path -LiteralPath $installerPath)) {
    throw (
        "Installer compilation completed but the expected " +
        "installer was not found: $installerPath"
    )
}


$installer = Get-Item -LiteralPath $installerPath

$sha256 = (
    Get-FileHash `
        -LiteralPath $installerPath `
        -Algorithm SHA256
).Hash


Write-Host ""
Write-Host "[OK] Windows installer built" `
    -ForegroundColor Green

Write-Host "Installer: $installerPath"
Write-Host (
    "Size:      {0:N1} MB" -f (
        $installer.Length / 1MB
    )
)
Write-Host "SHA256:    $sha256"