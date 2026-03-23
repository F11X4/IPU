Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-EdgeExecutablePath {
    $candidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Microsoft Edge is not installed. Install Edge first, then rerun bootstrap.ps1."
}

function Get-EdgeDriverArchiveName {
    if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
        return "edgedriver_arm64.zip"
    }

    return "edgedriver_win64.zip"
}

function Ensure-EdgeDriver {
    param(
        [string]$RepoRoot
    )

    $edgeExe = Get-EdgeExecutablePath
    $edgeVersion = (Get-Item $edgeExe).VersionInfo.ProductVersion
    $driverPath = Join-Path $RepoRoot "msedgedriver.exe"
    $driverVersion = $null

    if (Test-Path $driverPath) {
        $driverVersion = (Get-Item $driverPath).VersionInfo.ProductVersion
    }

    if ($driverVersion -eq $edgeVersion) {
        Write-Host "Local msedgedriver.exe already matches Edge $edgeVersion."
        return
    }

    $archiveName = Get-EdgeDriverArchiveName
    $downloadUrl = "https://msedgedriver.microsoft.com/$edgeVersion/$archiveName"
    $tempZip = Join-Path $env:TEMP "msedgedriver-$edgeVersion.zip"
    $extractDir = Join-Path $env:TEMP "msedgedriver-$edgeVersion"

    if (Test-Path $tempZip) {
        Remove-Item $tempZip -Force
    }

    if (Test-Path $extractDir) {
        Remove-Item $extractDir -Recurse -Force
    }

    Write-Host "Downloading EdgeDriver $edgeVersion..."
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tempZip

    Expand-Archive -Path $tempZip -DestinationPath $extractDir -Force
    Copy-Item (Join-Path $extractDir "msedgedriver.exe") $driverPath -Force

    Remove-Item $tempZip -Force
    Remove-Item $extractDir -Recurse -Force

    Write-Host "Installed local msedgedriver.exe for Edge $edgeVersion."
}

function Test-PythonCommand {
    param(
        [string[]]$PythonCommand
    )

    if (-not $PythonCommand -or $PythonCommand.Count -eq 0) {
        return $false
    }

    $pythonExe = $PythonCommand[0]
    $pythonBaseArgs = @()
    if ($PythonCommand.Length -gt 1) {
        $pythonBaseArgs = $PythonCommand[1..($PythonCommand.Length - 1)]
    }

    $versionScript = 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)'

    try {
        & $pythonExe @pythonBaseArgs -c $versionScript | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Get-PythonCommand {
    $commandCandidates = @(
        @("py", "-3"),
        @("python")
    )

    foreach ($commandCandidate in $commandCandidates) {
        if (Get-Command $commandCandidate[0] -ErrorAction SilentlyContinue) {
            if (Test-PythonCommand -PythonCommand $commandCandidate) {
                return $commandCandidate
            }
        }
    }

    $pythonCandidates = @()

    if ($env:LOCALAPPDATA) {
        $pythonCandidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Programs\Python") -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object { $_.FullName }
    }

    if ($env:ProgramFiles) {
        $pythonCandidates += Get-ChildItem -Path $env:ProgramFiles -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*\Python*\python.exe" } |
            Sort-Object FullName -Descending |
            ForEach-Object { $_.FullName }
    }

    foreach ($candidate in $pythonCandidates | Select-Object -Unique) {
        if (Test-Path $candidate) {
            $resolvedCandidate = @($candidate)
            if (Test-PythonCommand -PythonCommand $resolvedCandidate) {
                return $resolvedCandidate
            }
        }
    }

    return $null
}

function Ensure-Python {
    $pythonCommand = Get-PythonCommand
    if ($pythonCommand) {
        return $pythonCommand
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3 is not installed and winget is unavailable. Install Python 3 manually, then rerun bootstrap.ps1."
    }

    Write-Host "Python 3 not found. Installing Python with winget..."
    winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed to install Python 3."
    }

    $pythonCommand = Get-PythonCommand
    if (-not $pythonCommand) {
        throw "Python 3 was installed but is not available to this session yet. Open a new PowerShell window and rerun bootstrap.ps1."
    }

    return $pythonCommand
}

function Invoke-Python {
    param(
        [string[]]$PythonCommand,
        [string[]]$Arguments
    )

    $pythonExe = $PythonCommand[0]
    $pythonBaseArgs = @()
    if ($PythonCommand.Length -gt 1) {
        $pythonBaseArgs = $PythonCommand[1..($PythonCommand.Length - 1)]
    }

    & $pythonExe @pythonBaseArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

Ensure-EdgeDriver -RepoRoot $repoRoot

$pythonCommand = Ensure-Python
$venvPath = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    Invoke-Python -PythonCommand $pythonCommand -Arguments @("-m", "venv", ".venv")
}

try {
    Write-Host "Installing Python dependencies..."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip."
    }

    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Python dependencies."
    }

    Write-Host "Starting script..."
    & $venvPython instagram_post_unliker.py
    if ($LASTEXITCODE -ne 0) {
        throw "Script exited with an error."
    }
}
catch {
    Write-Error $_
    Read-Host "Bootstrap failed. Press Enter to close"
    exit 1
}
