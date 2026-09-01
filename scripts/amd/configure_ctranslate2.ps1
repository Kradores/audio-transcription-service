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
    ),

    [switch]$Reconfigure
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


function Assert-CacheValue {
    param(
        [Parameter(Mandatory)]
        [string[]]$CacheLines,

        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Expected
    )

    $prefix = "$Name`:"
    $line = $CacheLines |
        Where-Object {
            $_.StartsWith(
                $prefix,
                [System.StringComparison]::Ordinal
            )
        } |
        Select-Object -First 1

    if ($null -eq $line) {
        throw "CMake cache entry not found: $Name"
    }

    $separatorIndex = $line.IndexOf("=")

    if ($separatorIndex -lt 0) {
        throw "Invalid CMake cache entry: $line"
    }

    $actual = $line.Substring($separatorIndex + 1)

    if ($actual -ne $Expected) {
        throw (
            "CMake cache mismatch for $Name. " +
            "Expected='$Expected' Actual='$actual'"
        )
    }

    Write-Success "$Name = $actual"
}


function Assert-CacheContains {
    param(
        [Parameter(Mandatory)]
        [string[]]$CacheLines,

        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$ExpectedFragment
    )

    $prefix = "$Name`:"
    $line = $CacheLines |
        Where-Object {
            $_.StartsWith(
                $prefix,
                [System.StringComparison]::Ordinal
            )
        } |
        Select-Object -First 1

    if ($null -eq $line) {
        throw "CMake cache entry not found: $Name"
    }

    $separatorIndex = $line.IndexOf("=")

    if ($separatorIndex -lt 0) {
        throw "Invalid CMake cache entry: $line"
    }

    $actual = $line.Substring($separatorIndex + 1)

    $fragmentIndex = $actual.IndexOf(
        $ExpectedFragment,
        [System.StringComparison]::OrdinalIgnoreCase
    )

    if ($fragmentIndex -lt 0) {
        throw (
            "CMake cache entry '$Name' does not contain " +
            "'$ExpectedFragment'. Actual='$actual'"
        )
    }

    Write-Success "$Name contains '$ExpectedFragment'"
}


Write-Step "Validate prerequisites"

& (
    Join-Path `
        $PSScriptRoot `
        "test_prerequisites.ps1"
) `
    -PythonPath $PythonPath `
    -ToolchainPath $ToolchainPath

if ($LASTEXITCODE -ne 0) {
    throw "AMD build prerequisite validation failed."
}


$toolchain = Get-Content `
    -LiteralPath $ToolchainPath `
    -Raw |
    ConvertFrom-Json

$ct2 = $toolchain.required.ctranslate2
$oneApiVersion = $toolchain.required.intel_oneapi.version


$sourcePath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)"

$buildPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-build"

$installPath = Join-Path `
    $WorkspaceRoot `
    "CTranslate2-$($ct2.version)-install"

$openMpStagePath = Join-Path `
    $WorkspaceRoot `
    "intel-openmp-$oneApiVersion"


$resolvedPython = Resolve-Path -LiteralPath $PythonPath
$pythonScriptsPath = Split-Path -Parent $resolvedPython.Path

$cmakePath = Join-Path `
    $pythonScriptsPath `
    "cmake.exe"

$ninjaPath = Join-Path `
    $pythonScriptsPath `
    "ninja.exe"


$sitePackages = (
    & $resolvedPython.Path -c (
        "import sysconfig; " +
        "print(sysconfig.get_paths()['purelib'])"
    )
).Trim()

if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve Python site-packages."
}


$rocmDevelRoot = Join-Path `
    $sitePackages `
    "_rocm_sdk_devel"

$clangPath = Join-Path `
    $rocmDevelRoot `
    "lib\llvm\bin\clang.exe"

$clangxxPath = Join-Path `
    $rocmDevelRoot `
    "lib\llvm\bin\clang++.exe"


$openMpIncludePath = Join-Path `
    $openMpStagePath `
    "include"

$openMpLibraryPath = Join-Path `
    $openMpStagePath `
    "lib\libiomp5md.lib"


foreach ($requiredPath in @(
    $sourcePath,
    $cmakePath,
    $ninjaPath,
    $clangPath,
    $clangxxPath,
    $openMpIncludePath,
    $openMpLibraryPath
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required build path not found: $requiredPath"
    }
}


if ($Reconfigure -and (Test-Path -LiteralPath $buildPath)) {
    Write-Step "Clear previous CMake configuration"

    Remove-Item `
        -LiteralPath $buildPath `
        -Recurse `
        -Force
}


New-Item `
    -ItemType Directory `
    -Path @(
        $buildPath,
        $installPath
    ) `
    -Force |
    Out-Null


Write-Step "Configure CTranslate2"


$cxxFlags = (
    "-I" +
    '"' +
    $openMpIncludePath +
    '"'
)

& $cmakePath `
    -S $sourcePath `
    -B $buildPath `
    -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$ninjaPath" `
    "-DCMAKE_BUILD_TYPE=Release" `
    "-DCMAKE_INSTALL_PREFIX=$installPath" `
    "-DCMAKE_C_COMPILER=$clangPath" `
    "-DCMAKE_CXX_COMPILER=$clangxxPath" `
    "-DCMAKE_HIP_COMPILER=$clangxxPath" `
    "-DCMAKE_HIP_ARCHITECTURES=$($ct2.hip_architecture)" `
    "-DWITH_HIP=ON" `
    "-DWITH_CUDA=OFF" `
    "-DWITH_CUDNN=OFF" `
    "-DWITH_MKL=OFF" `
    "-DWITH_DNNL=OFF" `
    "-DWITH_OPENBLAS=OFF" `
    "-DWITH_RUY=OFF" `
    "-DCUDA_DYNAMIC_LOADING=OFF" `
    "-DENABLE_CPU_DISPATCH=ON" `
    "-DBUILD_CLI=OFF" `
    "-DBUILD_TESTS=OFF" `
    "-DBUILD_SHARED_LIBS=ON" `
    "-DOPENMP_RUNTIME=$($ct2.openmp_runtime)" `
    "-DIOMP5_LIBRARY=$openMpLibraryPath" `
    "-DCMAKE_CXX_FLAGS=$cxxFlags"

if ($LASTEXITCODE -ne 0) {
    throw "CTranslate2 CMake configuration failed."
}


Write-Step "Validate CMake configuration"


$cachePath = Join-Path `
    $buildPath `
    "CMakeCache.txt"

if (-not (Test-Path -LiteralPath $cachePath)) {
    throw "CMake cache was not created: $cachePath"
}

$cacheLines = @(
    Get-Content -LiteralPath $cachePath |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        }
)


Assert-CacheValue `
    -CacheLines $cacheLines `
    -Name "CMAKE_BUILD_TYPE" `
    -Expected "Release"

Assert-CacheValue `
    -CacheLines $cacheLines `
    -Name "WITH_HIP" `
    -Expected "ON"

Assert-CacheValue `
    -CacheLines $cacheLines `
    -Name "WITH_CUDA" `
    -Expected "OFF"

Assert-CacheValue `
    -CacheLines $cacheLines `
    -Name "WITH_CUDNN" `
    -Expected "OFF"

Assert-CacheValue `
    -CacheLines $cacheLines `
    -Name "OPENMP_RUNTIME" `
    -Expected "INTEL"

Assert-CacheValue `
    -CacheLines $cacheLines `
    -Name "CMAKE_HIP_ARCHITECTURES" `
    -Expected $ct2.hip_architecture

Assert-CacheContains `
    -CacheLines $cacheLines `
    -Name "IOMP5_LIBRARY" `
    -ExpectedFragment "libiomp5md.lib"

Assert-CacheContains `
    -CacheLines $cacheLines `
    -Name "CMAKE_CXX_FLAGS" `
    -ExpectedFragment $openMpIncludePath


$openMpFlagsLine = $cacheLines |
    Where-Object {
        $_ -match "^OpenMP_CXX_FLAGS:"
    } |
    Select-Object -First 1

if ($null -eq $openMpFlagsLine) {
    throw "OpenMP_CXX_FLAGS is missing from CMake cache."
}

if (
    $openMpFlagsLine -notmatch
    "-fopenmp=libomp"
) {
    throw (
        "CMake did not enable the expected Intel/LLVM OpenMP flags. " +
        "Actual='$openMpFlagsLine'"
    )
}

Write-Success "OpenMP_CXX_FLAGS contains -fopenmp=libomp"


Write-Host ""
Write-Host (
    "CTranslate2 configuration validated successfully."
) -ForegroundColor Green

Write-Host ""
Write-Host "Source:  $sourcePath"
Write-Host "Build:   $buildPath"
Write-Host "Install: $installPath"