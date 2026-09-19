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
    $repositoryRoot `
    "scripts\amd\stage_runtime.py"

$specPath = Join-Path `
    $repositoryRoot `
    "packaging\windows\AudioTranscriptionService-Amd.spec"

$runtimeDirectory = Join-Path `
    $repositoryRoot `
    "build\amd-runtime"

$distributionMetadataPath = Join-Path `
    $repositoryRoot `
    "build\distribution-metadata\amd\distribution-metadata.json"

$workDirectory = Join-Path `
    $repositoryRoot `
    "build\pyinstaller-amd"

$distDirectory = Join-Path `
    $repositoryRoot `
    "dist\amd"

$outputPath = Join-Path `
    $distDirectory `
    "AudioTranscriptionService"

$executablePath = Join-Path `
    $outputPath `
    "AudioTranscriptionService.exe"

$packagedInternal = Join-Path `
    $outputPath `
    "_internal"

$packagedDistributionMetadataPath = Join-Path `
    $packagedInternal `
    "distribution-metadata.json"


Write-Step "Validate AMD build inputs"

Assert-File $amdPython
Assert-File $stageRuntimeScript
Assert-File $specPath

Write-Success "AMD build environment is available"


Write-Step "Prepare reduced AMD runtime"

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

Write-Success "AMD runtime staged"


Write-Step "Generate AMD distribution metadata"

Push-Location $repositoryRoot

try {
    & $amdPython `
        -m scripts.generate_distribution_metadata `
        --profile amd `
        --project-root $repositoryRoot `
        --output $distributionMetadataPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "AMD distribution metadata generation failed " +
            "with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}

Assert-File $distributionMetadataPath

Write-Success "AMD distribution metadata generated"


Write-Step "Clean previous AMD package"

Remove-Item `
    -LiteralPath $distDirectory `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    -LiteralPath $workDirectory `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue


Write-Step "Build AMD Windows application"

Push-Location $repositoryRoot

try {
    & $amdPython `
        -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distDirectory `
        --workpath $workDirectory `
        $specPath

    if ($LASTEXITCODE -ne 0) {
        throw (
            "AMD PyInstaller build failed with exit code " +
            $LASTEXITCODE
        )
    }
}
finally {
    Pop-Location
}


Assert-File $executablePath
Assert-File $packagedDistributionMetadataPath


Write-Step "Validate packaged distribution metadata"

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

if (
    $sourceMetadataHash `
    -ne $packagedMetadataHash
) {
    throw (
        "Packaged AMD distribution metadata does not " +
        "match generated build metadata"
    )
}

Write-Success "Distribution metadata matches"


Write-Step "Validate packaged AMD runtime"

$requiredRuntimeFiles = @(
    "_rocm_sdk_core\bin\amd_comgr.dll",
    "_rocm_sdk_core\bin\amdhip64_7.dll",
    "_rocm_sdk_libraries\bin\hipblas.dll",
    "_rocm_sdk_libraries\bin\hiprand.dll",
    "ctranslate2\ctranslate2.dll",
    "ctranslate2\libiomp5md.dll"
)

foreach ($relativePath in $requiredRuntimeFiles) {
    Assert-File (
        Join-Path `
            $packagedInternal `
            $relativePath
    )
}

Write-Success "Required AMD runtime files are packaged"


$sizeBytes = (
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
    "[OK] AMD Windows application built"
) -ForegroundColor Green

Write-Host "Application: $outputPath"
Write-Host (
    "Size:        {0:N1} MB" -f (
        $sizeBytes / 1MB
    )
)