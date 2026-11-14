# GitFlow Assistant installer for Windows 10/11 (PowerShell 5.1+ or PowerShell 7).
# Installs for the current user only - no administrator rights required.
#   - checks Python (>= 3.9, via the "py" launcher or python.exe) and Git
#   - creates an isolated virtual environment in %LOCALAPPDATA%\gitflow-assistant\venv
#   - adds the venv Scripts folder to the *user* PATH (after confirmation)
# Run:  powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1 [-NoExtras] [-NoPath]
[CmdletBinding()]
param(
    [switch]$NoExtras,
    [switch]$NoPath
)
$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host "[i] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

$SrcDir  = Split-Path -Parent $PSScriptRoot
$AppHome = Join-Path $env:LOCALAPPDATA 'gitflow-assistant'
$Venv    = Join-Path $AppHome 'venv'
$Scripts = Join-Path $Venv 'Scripts'

# Python
$Python = $null
foreach ($candidate in @(@('py', '-3'), @('python'))) {
    $exe = $candidate[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $args0 = @($candidate | Select-Object -Skip 1)
        & $exe @args0 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
    }
}
if (-not $Python) { Fail 'Python 3.9+ not found. Install it: winget install Python.Python.3.12 (or python.org)' }
$PyExe = $Python[0]; $PyArgs = @($Python | Select-Object -Skip 1)
Ok ("Python: " + (& $PyExe @PyArgs --version))

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail 'Git not found. Install it: winget install --id Git.Git -e (or https://git-scm.com/download/win)'
}
Ok (git --version)

# Virtual environment
New-Item -ItemType Directory -Force -Path $AppHome | Out-Null
if (-not (Test-Path (Join-Path $Scripts 'python.exe'))) {
    Info "Creating virtual environment in $Venv"
    & $PyExe @PyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the virtual environment' }
}
$VenvPy = Join-Path $Scripts 'python.exe'
& $VenvPy -m pip install --quiet --upgrade pip
$Target = if ($NoExtras) { $SrcDir } else { "$SrcDir[full]" }
& $VenvPy -m pip install --quiet $Target
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed' }
Ok "Installed into $Venv"

# Command registration (user PATH)
$Gitflow = Join-Path $Scripts 'gitflow.exe'
if (-not (Test-Path $Gitflow)) { Fail "gitflow.exe not found in $Scripts" }
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $NoPath -and -not (($UserPath -split ';') -contains $Scripts)) {
    $answer = Read-Host "Add $Scripts to your user PATH? [Y/n]"
    if ($answer -eq '' -or $answer -match '^[yYsS]') {
        $newPath = if ([string]::IsNullOrEmpty($UserPath)) { $Scripts } else { "$UserPath;$Scripts" }
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        $env:Path = "$env:Path;$Scripts"
        Ok 'User PATH updated (open a new terminal to use "gitflow").'
    } else {
        Info "Run it with: & '$Gitflow'"
    }
}

# Verification
& $Gitflow --version
if ($LASTEXITCODE -ne 0) { Fail 'Verification failed' }
Ok 'Installation verified.'
Write-Host ''
Write-Host 'Next: gitflow doctor   |   gitflow (interactive menu)   |   gitflow upload'
Write-Host "Uninstall: remove $Venv and the PATH entry ($Scripts)."
