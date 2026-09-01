# Camera AI - Windows-app update (utan git).
# Laddar ner senaste koden som ZIP direkt från GitHub (ingen git krävs),
# installerar ev. nya beroenden och startar om aktiviteten/tjänsten. Lokala
# filer (.env, uploads/, media/, .venv, loggar och exporterade
# OpenVINO-modeller) bevaras.
#
#   powershell -ExecutionPolicy Bypass -File windows\update.ps1
param(
    [string]$Branch = "main",
    [string]$Owner = "nikeng-forenade",
    [string]$Repo = "camera_ai"
)
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot
$TaskName = "CameraAI"
$ZipUrl = "https://github.com/$Owner/$Repo/archive/refs/heads/$Branch.zip"
$Temp = Join-Path $env:TEMP ("camera_ai_update_" + $PID)
$Zip = Join-Path $Temp "$Branch.zip"
$Staging = Join-Path $Temp "extracted"

Write-Host "=== Camera AI update (branch: $Branch) ===" -ForegroundColor Cyan
Write-Host "Hämtar: $ZipUrl"

New-Item -ItemType Directory -Path $Temp -Force | Out-Null

# 1. Ladda ner senaste koden som ZIP (ingen git behövs)
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $ZipUrl -OutFile $Zip -UseBasicParsing
} catch {
    & curl.exe -L -o $Zip $ZipUrl   # fallback (finns på Windows 10+)
}
if (-not (Test-Path $Zip) -or (Get-Item $Zip).Length -lt 1000) {
    Write-Host "Nedladdning misslyckades - kontrollera internetåtkomst och att '$Owner/$Repo' finns." -ForegroundColor Red
    exit 1
}

# 2. Packa upp
Expand-Archive -Path $Zip -DestinationPath $Staging -Force
$RepoRoot = Get-ChildItem $Staging -Directory | Select-Object -First 1
if (-not $RepoRoot) {
    Write-Host "Kunde inte packa upp arkivet." -ForegroundColor Red
    exit 1
}

# 3. Kopiera kodfiler till app-mappen.
#    Skyddar lokala filer: .env, uploads/, media/, .venv, loggar och
#    exporterade OpenVINO-modeller (t.ex. yolo11n_openvino_model/).
robocopy $RepoRoot.FullName $AppDir /E `
    /XD .venv uploads media __pycache__ build dist .git `
    /XF .env *.log *_openvino_model `
    /NFL /NDL /NJH /NJS /NP | Out-Null
# robocopy exitkod: 0-7 = lyckat (1 = filer kopierade), 8+ = fel
if ($LASTEXITCODE -gt 7) {
    Write-Host "Kopiering misslyckades (robocopy kod $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# 4. Beroenden (no-op om oförändrade)
$Py = "$AppDir\.venv\Scripts\python.exe"
if (Test-Path $Py) {
    & $Py -m pip install -r "$AppDir\requirements.txt" 2>&1 | Out-Host
} else {
    Write-Host "Varning: $Py saknas - kör windows\setup.ps1 först." -ForegroundColor Yellow
}

# 4b. Uppgradera Ollama (krävs bl.a. för llama3.2-vision / mllama-stöd)
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Kontrollerar nyare Ollama-version ..." -ForegroundColor Cyan
    try {
        & winget upgrade --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
        Write-Host ("Ollama: " + (ollama --version 2>&1)) -ForegroundColor Green
    } catch {
        Write-Host "Ollama-uppgradering hoppades över: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 5. Stoppa körande app (fönstret/tray-ikonen eller aktiviteten)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='CameraAI.exe'" |
    Where-Object { $_.CommandLine -match "camera_ai_app\.py|--server" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 6. Starta om aktiviteten/tjänsten om den är installerad
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Aktiviteten '$TaskName' startades om." -ForegroundColor Green
} elseif (Get-Service -Name "camera-ai" -ErrorAction SilentlyContinue) {
    Restart-Service -Name "camera-ai" -Force
    Write-Host "Tjänsten 'camera-ai' startades om." -ForegroundColor Green
} else {
    Write-Host "Ingen aktivitet/tjänst installerad - starta med:  .\windows\start.bat" -ForegroundColor Yellow
}

# 7. Städa temp
Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Klart! Uppdateringen är på plats." -ForegroundColor Green
