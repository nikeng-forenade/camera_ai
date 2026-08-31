# Camera AI - Windows-app update (Arc B50 Pro / Vulkan).
# Pullar senaste koden fr\u00e5n GitHub, installerar ev. nya beroenden och stoppar
# den k\u00f6rande appen s\u00e5 du kan starta om den. Ingen EXE-byggning beh\u00f6vs.
#
#   powershell -ExecutionPolicy Bypass -File windows\update.ps1
param(
    [string]$Branch = "main"
)
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot

Write-Host "=== Camera AI update (branch: $Branch) ==="

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: git saknas - installera https://git-scm.com" -ForegroundColor Red
    exit 1
}

Set-Location $AppDir

# 1. H\u00e4mta senaste kod
git fetch origin
git checkout $Branch
git pull --ff-only

# 2. Beroenden (no-op om of\u00f6r\u00e4ndrade)
& "$AppDir\.venv\Scripts\python.exe" -m pip install -r requirements.txt

# 3. Stoppa k\u00f6rande app (f\u00f6nstret/tray-ikonen)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -match "camera_ai_app\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "Uppdaterat! Starta igen med:  .\windows\start.bat" -ForegroundColor Green
