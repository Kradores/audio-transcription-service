[CmdletBinding()]
param(
    [string]$PythonPath = ".venv-therock\Scripts\python.exe",

    [string]$ToolchainPath = (
        Join-Path $PSScriptRoot "toolchain.json"
    )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


function Write-Success {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host "[OK] $Message" -ForegroundColor Green
}


function Write-VersionWarning {
    param(
        [Parameter(Mandatory)]
        [string]$Component,

        [Parameter(Mandatory)]
        [string]$Expected,

        [Parameter(Mandatory)]
        [string]$Actual
    )

    Write-Warning (
        "$Component differs from the known-good build. " +
        "Observed='$Actual' KnownGood='$Expected'"
    )
}


function Assert-Equal {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Expected,

        [Parameter(Mandatory)]
        [string]$Actual
    )

    if ($Actual -ne $Expected) {
        throw (
            "$Name mismatch. " +
            "Expected='$Expected' Actual='$Actual'"
        )
    }

    Write-Success "$Name = $Actual"
}


function Assert-FileExists {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }

    Write-Success "$Description found"
}


function Assert-CommandExists {
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue

    if ($null -eq $command) {
        throw "Required command not found: $Name"
    }

    Write-Success "$Name found"
}


function Get-CommandVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [Parameter(Mandatory)]
        [string]$Pattern
    )

    $output = (& $Name @Arguments 2>&1) -join "`n"

    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed while reading its version.`n$output"
    }

    $match = [regex]::Match($output, $Pattern)

    if (-not $match.Success) {
        throw "Could not parse $Name version from:`n$output"
    }

    return $match.Groups[1].Value
}


function Test-MsvcEnvironmentInitialized {
    $clCommand = Get-Command `
        "cl" `
        -ErrorAction SilentlyContinue

    $linkCommand = Get-Command `
        "link" `
        -ErrorAction SilentlyContinue

    return (
        $null -ne $clCommand -and
        $null -ne $linkCommand -and
        -not [string]::IsNullOrWhiteSpace($env:VCINSTALLDIR) -and
        -not [string]::IsNullOrWhiteSpace($env:WindowsSdkDir) -and
        -not [string]::IsNullOrWhiteSpace($env:INCLUDE) -and
        -not [string]::IsNullOrWhiteSpace($env:LIB)
    )
}


function Initialize-MsvcEnvironment {
    param(
        [string]$Architecture = "x64"
    )

    if (Test-MsvcEnvironmentInitialized) {
        Write-Success (
            "Visual Studio C++ environment already initialized"
        )

        if (
            -not [string]::IsNullOrWhiteSpace(
                $env:VSINSTALLDIR
            )
        ) {
            return $env:VSINSTALLDIR.TrimEnd(
                [char[]]@("\", "/")
            )
        }

        return "existing environment"
    }

    $programFilesX86 = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::ProgramFilesX86
    )

    $vswherePath = Join-Path `
        $programFilesX86 `
        "Microsoft Visual Studio\Installer\vswhere.exe"

    Assert-FileExists `
        -Path $vswherePath `
        -Description "Visual Studio locator"

    $installationPath = (
        & $vswherePath `
            -latest `
            -products "*" `
            -requires "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" `
            -property installationPath
    ).Trim()

    if ($LASTEXITCODE -ne 0) {
        throw "vswhere failed while locating Visual C++."
    }

    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        throw (
            "No Visual Studio installation with the " +
            "C++ x64 build tools was found."
        )
    }

    $vsDevCmdPath = Join-Path `
        $installationPath `
        "Common7\Tools\VsDevCmd.bat"

    Assert-FileExists `
        -Path $vsDevCmdPath `
        -Description "Visual Studio developer environment"

    $command = (
        'call "{0}" -no_logo -arch={1} -host_arch={1} >nul && set'
    ) -f $vsDevCmdPath, $Architecture

    $environmentLines = @(
        & $env:ComSpec /d /s /c $command
    )

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Failed to initialize the Visual Studio " +
            "developer environment."
        )
    }

    foreach ($line in $environmentLines) {
        $separatorIndex = $line.IndexOf("=")

        if ($separatorIndex -le 0) {
            continue
        }

        $name = $line.Substring(
            0,
            $separatorIndex
        )

        $value = $line.Substring(
            $separatorIndex + 1
        )

        [Environment]::SetEnvironmentVariable(
            $name,
            $value,
            "Process"
        )
    }

    if (-not (Test-MsvcEnvironmentInitialized)) {
        throw (
            "Visual Studio developer environment was imported, " +
            "but required C++ variables are incomplete."
        )
    }

    return $installationPath
}


$isWindowsPlatform = $env:OS -eq "Windows_NT"

if (-not $isWindowsPlatform) {
    throw "AMD/TheRock build tooling currently supports Windows only."
}

Write-Success "Windows platform detected"
Write-Success (
    "PowerShell = " +
    $PSVersionTable.PSVersion.ToString()
)


$toolchainFile = Resolve-Path -LiteralPath $ToolchainPath

$toolchain = Get-Content `
    -LiteralPath $toolchainFile `
    -Raw |
    ConvertFrom-Json


if ($toolchain.schema_version -ne 1) {
    throw (
        "Unsupported toolchain schema version: " +
        $toolchain.schema_version
    )
}

Write-Success "toolchain schema version 1"


$resolvedPython = Resolve-Path -LiteralPath $PythonPath

$pythonScriptsDirectory = Split-Path `
    -Parent `
    $resolvedPython.Path

$cmakePath = Join-Path `
    $pythonScriptsDirectory `
    "cmake.exe"

$ninjaPath = Join-Path `
    $pythonScriptsDirectory `
    "ninja.exe"

$pythonVersion = (
    & $resolvedPython.Path -c (
        "import sys; " +
        "print('.'.join(map(str, sys.version_info[:3])))"
    )
).Trim()

if ($LASTEXITCODE -ne 0) {
    throw "Failed to execute Python: $resolvedPython"
}

Assert-Equal `
    -Name "Python" `
    -Expected $toolchain.required.python `
    -Actual $pythonVersion


Assert-CommandExists "uv"

Assert-FileExists `
    -Path $cmakePath `
    -Description "CMake"

Assert-FileExists `
    -Path $ninjaPath `
    -Description "Ninja"

$visualStudioPath = Initialize-MsvcEnvironment

Write-Success (
    "Visual Studio C++ environment ready: " +
    $visualStudioPath
)

Assert-CommandExists "cl"
Assert-CommandExists "link"
Assert-CommandExists "dumpbin"


$uvVersionOutput = (
    uv --version
).Trim()

$uvVersionMatch = [regex]::Match(
    $uvVersionOutput,
    "^uv\s+([^\s]+)"
)

if (-not $uvVersionMatch.Success) {
    throw "Could not parse uv version from: $uvVersionOutput"
}

$uvVersion = $uvVersionMatch.Groups[1].Value

if (
    $uvVersion -ne
    $toolchain.observed_build_tools.uv
) {
    Write-VersionWarning `
        -Component "uv" `
        -Expected $toolchain.observed_build_tools.uv `
        -Actual $uvVersion
}
else {
    Write-Success "uv = $uvVersion"
}


$cmakeVersion = Get-CommandVersion `
    -Name $cmakePath `
    -Arguments @("--version") `
    -Pattern "cmake version ([^\s]+)"

if (
    $cmakeVersion -ne
    $toolchain.observed_build_tools.cmake
) {
    Write-VersionWarning `
        -Component "CMake" `
        -Expected $toolchain.observed_build_tools.cmake `
        -Actual $cmakeVersion
}
else {
    Write-Success "CMake = $cmakeVersion"
}


$ninjaVersion = (
    & $ninjaPath --version
).Trim()

if ($LASTEXITCODE -ne 0) {
    throw "Failed to read Ninja version."
}

if (
    $ninjaVersion -ne
    $toolchain.observed_build_tools.ninja
) {
    Write-VersionWarning `
        -Component "Ninja" `
        -Expected $toolchain.observed_build_tools.ninja `
        -Actual $ninjaVersion
}
else {
    Write-Success "Ninja = $ninjaVersion"
}


$freezeLines = @(
    uv pip freeze `
        --python $resolvedPython.Path
)

if ($LASTEXITCODE -ne 0) {
    throw "Failed to inspect TheRock Python packages with uv."
}


foreach (
    $packageProperty in
    $toolchain.required.therock.packages.PSObject.Properties
) {
    $packageName = $packageProperty.Name
    $expectedVersion = [string]$packageProperty.Value

    $pattern = (
        "^" +
        [regex]::Escape($packageName) +
        "==(.+)$"
    )

    $matchingLine = $freezeLines |
        Where-Object {
            $_ -match $pattern
        } |
        Select-Object -First 1

    if ($null -eq $matchingLine) {
        throw (
            "Required TheRock package is not installed: " +
            $packageName
        )
    }

    $actualVersion = (
        [regex]::Match(
            $matchingLine,
            $pattern
        )
    ).Groups[1].Value

    Assert-Equal `
        -Name "TheRock package $packageName" `
        -Expected $expectedVersion `
        -Actual $actualVersion
}


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
    "lib\llvm\bin\clang++.exe"

$hipccPath = Join-Path `
    $rocmDevelRoot `
    "bin\hipcc.exe"

Assert-FileExists `
    -Path $clangPath `
    -Description "AMD clang++"

Assert-FileExists `
    -Path $hipccPath `
    -Description "HIP compiler driver"


$clangOutput = (
    & $clangPath --version 2>&1
) -join "`n"

if ($LASTEXITCODE -ne 0) {
    throw "AMD clang failed.`n$clangOutput"
}

$expectedClangVersion = (
    $toolchain.observed_build_tools.amd_clang.version
)

if (
    $clangOutput -notmatch
    [regex]::Escape($expectedClangVersion)
) {
    Write-Warning (
        "AMD clang differs from known-good version " +
        "'$expectedClangVersion'."
    )
}
else {
    Write-Success "AMD clang = $expectedClangVersion"
}


$hipccOutput = (
    & $hipccPath --version 2>&1
) -join "`n"

if ($LASTEXITCODE -ne 0) {
    throw "hipcc failed.`n$hipccOutput"
}

$expectedHipVersion = (
    $toolchain.observed_build_tools.hip
)

if (
    $hipccOutput -notmatch
    [regex]::Escape($expectedHipVersion)
) {
    Write-Warning (
        "HIP differs from known-good version " +
        "'$expectedHipVersion'."
    )
}
else {
    Write-Success "HIP = $expectedHipVersion"
}


$programFilesX86 = [Environment]::GetFolderPath(
    [Environment+SpecialFolder]::ProgramFilesX86
)

$oneApiVersion = (
    $toolchain.required.intel_oneapi.version
)

$oneApiRoot = Join-Path `
    $programFilesX86 `
    "Intel\oneAPI\compiler\$oneApiVersion"


foreach (
    $artifactProperty in
    $toolchain.required.intel_oneapi.artifacts.PSObject.Properties
) {
    $artifact = $artifactProperty.Value

    $artifactPath = Join-Path `
        $oneApiRoot `
        $artifact.relative_path

    Assert-FileExists `
        -Path $artifactPath `
        -Description "Intel oneAPI $($artifactProperty.Name)"

    if (
        $artifact.PSObject.Properties.Name -contains
        "sha256"
    ) {
        $actualHash = (
            Get-FileHash `
                -LiteralPath $artifactPath `
                -Algorithm SHA256
        ).Hash

        Assert-Equal `
            -Name "SHA256 $($artifactProperty.Name)" `
            -Expected $artifact.sha256 `
            -Actual $actualHash
    }
}


$rocmImportCheck = & $resolvedPython.Path -c (
    "import rocm_sdk; " +
    "print('rocm_sdk import ok')"
)

if ($LASTEXITCODE -ne 0) {
    throw "rocm_sdk cannot be imported."
}

Write-Success $rocmImportCheck.Trim()


Write-Host ""
Write-Host (
    "AMD/TheRock build prerequisites validated successfully."
) -ForegroundColor Green