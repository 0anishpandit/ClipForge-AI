<#
.SYNOPSIS  One-time setup: creates .venv and installs dependencies.
.EXAMPLE   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
           powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Dev   # also installs pytest
#>
param([switch]$Dev)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Find Python 3.10+: prefer the Windows "py" launcher, fall back to "python".
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe = "py"
    $PythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = "python"
    $PythonArgs = @()
} else {
    throw "Python 3.10+ was not found. Install it from https://www.python.org/downloads/ and tick 'Add Python to PATH'."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment in .venv ..."
    & $PythonExe @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}

$Requirements = if ($Dev) { "requirements-dev.txt" } else { "requirements.txt" }
Write-Host "Installing $Requirements ..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Write-Host "Tip: copy .env.example to .env to customise settings."
}

# Non-fatal checks for the two external programs.
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "FFmpeg was not found on PATH. Rendering needs it (or set CLIPFORGE_FFMPEG in .env)."
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Warning "Ollama was not found on PATH. AI analysis needs it: https://ollama.com/download"
}

Write-Host "`nSetup complete. Start the app with:  scripts\run.ps1"
