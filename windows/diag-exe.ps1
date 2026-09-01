# Camera AI - diagnostik av den byggda EXE:n. Skriver resultat till diag_out.txt
#   powershell -NoProfile -ExecutionPolicy Bypass -File windows\diag-exe.ps1
$ErrorActionPreference = "Stop"
$out = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\diag_out.txt"))
"" | Set-Content -Path $out -Encoding UTF8
function Log($m) { $m | Add-Content -Path $out -Encoding UTF8; Write-Host $m }

# Stoppa gamla instanser
Get-Process | Where-Object { $_.ProcessName -match "CameraAI" } | Stop-Process -Force -ErrorAction SilentlyContinue
Log "1) gamla CameraAI-processer stoppade"

$exe = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\dist\CameraAI\CameraAI.exe"))
Log ("2) exe: " + $exe)
$p = Start-Process -FilePath $exe -PassThru
Log ("3) startad PID=" + $p.Id)

Start-Sleep -Seconds 15
Log ("4) process lever efter 15s: " + (-not $p.HasExited))

try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 8 -UseBasicParsing
    Log ("5) HEALTH " + $r.StatusCode + ": " + $r.Content)
} catch {
    Log ("5) HEALTH FEL: " + $_.Exception.Message)
}

$applog = Join-Path (Split-Path $exe) "_internal\camera_ai.log"
if (Test-Path $applog) {
    Log "6) applogg (_internal\camera_ai.log):"
    Get-Content $applog -Tail 15 | ForEach-Object { Log ("   " + $_) }
} else {
    Log "6) ingen applogg i _internal"
}

Get-Process | Where-Object { $_.ProcessName -match "CameraAI" } | Stop-Process -Force -ErrorAction SilentlyContinue
Log "7) klart - exe stoppad, resultat i diag_out.txt"
