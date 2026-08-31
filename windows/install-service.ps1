# Camera AI - kör som Windows-tjänst via NSSM (valfritt, headless).
# 1) Ladda ner https://nssm.cc (nssm.exe) och lägg den i PATH eller i denna mapp.
# 2) Kör som admin:
#    powershell -ExecutionPolicy Bypass -File windows\install-service.ps1
param([string]$Nssm = "nssm.exe")
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot
$Py = "$AppDir\.venv\Scripts\pythonw.exe"
$Log = "$AppDir\windows\camera_ai.log"

if (-not (Test-Path $Py)) { Write-Host "Kör först: windows\setup.ps1" -ForegroundColor Red; exit 1 }
if (-not (Get-Command $Nssm -ErrorAction SilentlyContinue)) { Write-Host "hittar inte $Nssm - ladda ner https://nssm.cc" -ForegroundColor Red; exit 1 }

& $Nssm install camera-ai $Py "$AppDir\windows\camera_ai_app.py"
& $Nssm set camera-ai AppDirectory $AppDir
& $Nssm set camera-ai AppStdout $Log
& $Nssm set camera-ai AppStderr $Log
& $Nssm set camera-ai AppRotateFiles 1
& $Nssm set camera-ai Start SERVICE_AUTO_START
& $Nssm start camera-ai

Write-Host "Tjänsten 'camera-ai' installerad och startad (headless - GUI nås via http://<dator-ip>:8000)." -ForegroundColor Green
Write-Host "Avinstallera:  nssm remove camera-ai confirm"
