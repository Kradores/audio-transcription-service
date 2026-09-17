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

function Wait-DirectoryReadable {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [int]$TimeoutSeconds = 30
    )

    $deadline = (
        Get-Date
    ).AddSeconds($TimeoutSeconds)

    while ($true) {
        $blockedFile = $null

        foreach ($file in Get-ChildItem `
            -LiteralPath $Path `
            -Recurse `
            -File
        ) {
            try {
                $stream = [System.IO.File]::Open(
                    $file.FullName,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::Read,
                    (
                        [System.IO.FileShare]::ReadWrite `
                        -bor [System.IO.FileShare]::Delete
                    )
                )

                $stream.Dispose()
            }
            catch {
                $blockedFile = $file.FullName
                break
            }
        }

        if ($null -eq $blockedFile) {
            return
        }

        if ((Get-Date) -ge $deadline) {
            throw (
                "Timed out waiting for build files to become readable. " +
                "Blocked file: $blockedFile"
            )
        }

        Write-Host (
            "Waiting for build file lock to clear: " +
            $blockedFile
        )

        Start-Sleep -Milliseconds 500
    }
}


$repositoryRoot = (
    Resolve-Path `
        (Join-Path $PSScriptRoot "..\..")
).Path

$toolchainPath = Join-Path `
    $PSScriptRoot `
    "toolchain.json"

$toolchain = Get-Content `
    -LiteralPath $toolchainPath `
    -Raw |
    ConvertFrom-Json


$workspace = Join-Path `
    $repositoryRoot `
    "build\nvidia-smoke"

$packagesDirectory = Join-Path `
    $workspace `
    "packages"

$runtimeDirectory = Join-Path `
    $workspace `
    "runtime"

$distRoot = Join-Path `
    $repositoryRoot `
    "dist\nvidia-smoke"

$pyinstallerDist = Join-Path `
    $distRoot `
    "app"

$pyinstallerWork = Join-Path `
    $workspace `
    "pyinstaller"

$specPath = Join-Path `
    $repositoryRoot `
    "packaging\windows\NvidiaRuntimeSmokeTest.spec"

$zipPath = Join-Path `
    $distRoot `
    "AudioTranscriptionService-NvidiaSmokeTest.zip"


Write-Step "Prepare workspace"

Remove-Item `
    $workspace `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    $distRoot `
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
    -Path $runtimeDirectory `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path $distRoot `
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


Write-Step "Download pinned NVIDIA runtime packages"

& uv pip install `
    --target $packagesDirectory `
    --no-deps `
    @packageSpecifications

if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare NVIDIA runtime packages."
}


Write-Step "Stage required NVIDIA runtime DLLs"

$requiredDlls = @(
    $toolchain.nvidia.required_dlls
)

$manifestFiles = @()


foreach ($dllName in $requiredDlls) {
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
        $runtimeDirectory `
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
    $runtimeDirectory `
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


Write-Step "Validate smoke-test inputs"

Assert-File $manifestPath

Assert-File (
    Join-Path `
        $repositoryRoot `
        "tests\fixtures\audio\english_speech.wav"
)


Write-Step "Build NVIDIA smoke-test executable"

& uv run pyinstaller `
    --noconfirm `
    --clean `
    --distpath $pyinstallerDist `
    --workpath $pyinstallerWork `
    $specPath

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller NVIDIA smoke-test build failed."
}


$artifactDirectory = Join-Path `
    $pyinstallerDist `
    "NvidiaRuntimeSmokeTest"

$executablePath = Join-Path `
    $artifactDirectory `
    "NvidiaRuntimeSmokeTest.exe"

Assert-File $executablePath


Write-Step "Create distributable ZIP"

Wait-DirectoryReadable `
    -Path $artifactDirectory `
    -TimeoutSeconds 30

Remove-Item `
    -LiteralPath $zipPath `
    -Force `
    -ErrorAction SilentlyContinue

try {
    Compress-Archive `
        -Path (
            Join-Path `
                $artifactDirectory `
                "*"
        ) `
        -DestinationPath $zipPath `
        -CompressionLevel Optimal `
        -ErrorAction Stop
}
catch {
    throw (
        "Failed to create NVIDIA smoke-test ZIP: " +
        $_.Exception.Message
    )
}


$zip = Get-Item `
    -LiteralPath $zipPath

$zipHash = (
    Get-FileHash `
        -LiteralPath $zipPath `
        -Algorithm SHA256
).Hash


Write-Host ""
Write-Host (
    "[OK] NVIDIA smoke-test artifact built"
) -ForegroundColor Green

Write-Host "Artifact: $zipPath"
Write-Host (
    "Size:     {0:N1} MB" -f (
        $zip.Length / 1MB
    )
)
Write-Host "SHA256:   $zipHash"