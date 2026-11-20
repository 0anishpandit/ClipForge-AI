<#
.SYNOPSIS  Starts ClipForge AI from the project root.
.EXAMPLE   powershell -ExecutionPolicy Bypass -File scripts\run.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

# Calling the venv's python directly avoids needing to run Activate.ps1
# (which PowerShell's execution policy often blocks).
& $VenvPython -m streamlit run app.py @args
