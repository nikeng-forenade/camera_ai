# Camera AI - smoke test av den byggda EXE:n.
#   powershell -ExecutionPolicy Bypass -File windows\test-exe.ps1
param(
    [string]$Exe = ""
)
$ErrorActionPreference = "Stop"

if (-not $Exe) { $Exe = Join-Path $PSScriptRoot "..\dist\CameraAI\CameraAI.exe" }
$Exe = [System.IO.Path]::GetFullPath($Exe)
if (-not (Test-Path $Exe)) { Write-Host "hittar inte $Exe - bygg forst: windows\build_exe.ps1" -ForegroundColor Red; exit 1 }

# Stoppa ev. gamla instanser
Get-Process | Where-Object { $_.ProcessName -match "CameraAI" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "Startar $Exe ..."
$p = Start-Process -FilePath $Exe -PassThru
Start-Sleep -Seconds 15

$alive = -not $p.HasExited
Write-Host ("Process lever: " + $alive)

if (-not $alive) {
    Write-Host "Exe kraschade direkt." -ForegroundColor Red
    $log = Join-Path (Split-Path $Exe) "_internal\camera_ai.log"
    if (Test-Path $log) { Get-Content $log -Tail 30 } else { Write-Host "ingen logg: $log" -ForegroundColor Yellow }
    exit 1
}

try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 8 -UseBasicParsing
    Write-Host ("HEALTH " + $r.StatusCode + ": " + $r.Content) -ForegroundColor Green
} catch {
    Write-Host ("HEALTH FEL: " + $_.Exception.Message) -ForegroundColor Yellow
}

Get-Process | Where-Object { $_.ProcessName -match "CameraAI" } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Test klart - exe stoppad."
