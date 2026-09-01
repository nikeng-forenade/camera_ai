# Camera AI - total installation och uppdatering (allt i ett).
#
# Första körningen installerar allt som behövs på servern:
#   * hämtar senaste koden från GitHub som ZIP (ingen git krävs)
#   * Python 3.12 (installeras via winget om det saknas)
#   * virtuell miljö + beroenden (venv)
#   * Ollama + moondream-modellen (installeras via winget om det saknas)
#   * .env (skapas om det saknas)
#   * schemalagd aktivitet "CameraAI" (headless server på 0.0.0.0:8000)
#
# Kör du det igen fungerar det som UPPDATERING: ny kod laddas ner, beroenden
# uppdateras och aktiviteten startas om. Lokala filer (.env, uploads/, media/,
# .venv, loggar och exporterade OpenVINO-modeller) skrivs aldrig över.
#
# Kör som ADMINISTRATÖR:
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1
#
# Alternativ:
#   -SkipUpdate     Ladda inte ner ny kod först (använd befintlig)
#   -NoTask         Installera inte den schemalagda aktiviteten
#   -NoOllamaModel  Dra inte ner moondream-modellen
param(
    [string]$Branch = "main",
    [string]$Owner = "nikeng-forenade",
    [string]$Repo = "camera_ai",
    [switch]$SkipUpdate,
    [switch]$NoTask,
    [switch]$NoOllamaModel
)
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot
$TaskName = "CameraAI"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "VARNING: Kör inte som administratör - aktivitetsinstallation och winget kan misslyckas." -ForegroundColor Yellow
}

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " Camera AI - installation / uppdatering" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "App-katalog: $AppDir"

# ---------------------------------------------------------------------------
# 0. Hämta senaste koden (uppdatering) - ingen git krävs
# ---------------------------------------------------------------------------
if (-not $SkipUpdate) {
    Write-Host ""
    Write-Host "--- 0/6 Hämta senaste koden ($Branch) ---" -ForegroundColor Cyan
    $ZipUrl = "https://github.com/$Owner/$Repo/archive/refs/heads/$Branch.zip"
    $Temp = Join-Path $env:TEMP ("camera_ai_install_" + $PID)
    $Zip = Join-Path $Temp "$Branch.zip"
    $Staging = Join-Path $Temp "extracted"
    New-Item -ItemType Directory -Path $Temp -Force | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $ZipUrl -OutFile $Zip -UseBasicParsing
    } catch {
        & curl.exe -L -o $Zip $ZipUrl   # fallback (finns på Windows 10+)
    }
    if (Test-Path $Zip -and (Get-Item $Zip).Length -ge 1000) {
        Expand-Archive -Path $Zip -DestinationPath $Staging -Force
        $RepoRoot = Get-ChildItem $Staging -Directory | Select-Object -First 1
        if ($RepoRoot) {
            robocopy $RepoRoot.FullName $AppDir /E `
                /XD .venv uploads media __pycache__ build dist .git `
                /XF .env *.log *_openvino_model `
                /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -le 7) {
                Write-Host "Kod uppdaterad." -ForegroundColor Green
            } else {
                Write-Host "Kopiering av kod misslyckades (robocopy kod $LASTEXITCODE) - fortsätter." -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "Kunde inte hämta kod - fortsätter med befintlig." -ForegroundColor Yellow
    }
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
} else {
    Write-Host ""
    Write-Host "--- 0/6 Hoppar över kodhämtning (-SkipUpdate) ---" -ForegroundColor Yellow
}

if (-not (Test-Path "$AppDir\app.py")) {
    Write-Host "ERROR: Ingen kod hittad i $AppDir. Ladda ner repot eller kontrollera internetåtkomst." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Python 3.12 (installera via winget om det saknas)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "--- 1/6 Python ---" -ForegroundColor Cyan
$Py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Py = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Py = "python" }
if (-not $Py) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: varken Python eller winget finns. Installera Python 3.12 från https://python.org först." -ForegroundColor Red
        exit 1
    }
    Write-Host "Python saknas - installerar Python 3.12 via winget ..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $Py = "py"
}
if ($Py -eq "py") {
    Write-Host ("Python (py launcher): " + ((& py -3.12 --version 2>&1) -join " "))
} else {
    Write-Host ("Python: " + ((& python --version 2>&1) -join " "))
}

# ---------------------------------------------------------------------------
# 2. Virtuell miljö + beroenden
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "--- 2/6 Virtuell miljö + beroenden ---" -ForegroundColor Cyan
if (-not (Test-Path "$AppDir\.venv")) {
    Write-Host "Skapar .venv ..."
    if ($Py -eq "py") { & py -3.12 -m venv "$AppDir\.venv" } else { & python -m venv "$AppDir\.venv" }
}
$PyExe = "$AppDir\.venv\Scripts\python.exe"
if (-not (Test-Path $PyExe)) {
    Write-Host "ERROR: kunde inte skapa .venv" -ForegroundColor Red
    exit 1
}
& $PyExe -m pip install --upgrade pip
& $PyExe -m pip install -r "$AppDir\requirements.txt" openvino

# ---------------------------------------------------------------------------
# 3. .env (skapas bara om det saknas)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "--- 3/6 .env ---" -ForegroundColor Cyan
$EnvFile = "$AppDir\.env"
if (-not (Test-Path $EnvFile)) {
    @"
YOLO_MODEL=yolo11n.pt
YOLO_DEVICE=openvino:GPU
LLM_BACKEND=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=moondream
PORT=8000
"@ | Set-Content -Path $EnvFile -Encoding UTF8
    Write-Host ".env skapad (redigera vid behov)." -ForegroundColor Green
} else {
    Write-Host ".env finns redan - behålls."
}

# ---------------------------------------------------------------------------
# 4. Ollama + moondream (installera via winget om det saknas)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "--- 4/6 Ollama + moondream ---" -ForegroundColor Cyan
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: winget saknas - installera Ollama manuellt från https://ollama.com" -ForegroundColor Red
    } else {
        Write-Host "Ollama saknas - installerar via winget ..." -ForegroundColor Yellow
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    }
}
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    # Vulkan för Intel Arc (globalt om admin)
    if ($isAdmin) { [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "Machine") }
    $env:OLLAMA_VULKAN = "1"
    # Säkerställ att Ollama körs
    if (-not (Get-Process -Name "ollama*" -ErrorAction SilentlyContinue)) {
        Write-Host "Startar Ollama ..."
        Start-Process -FilePath (Get-Command ollama).Source -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
    if (-not $NoOllamaModel) {
        Write-Host "Laddar ner moondream (kan ta en stund) ..."
        ollama pull moondream
    }
} else {
    Write-Host "Ollama installerades inte - starta om PowerShell och kör igen, eller installera från https://ollama.com." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 5. Verifiera OpenVINO-enheter
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "--- 5/6 OpenVINO-enheter (Arc-kortet ska synas) ---" -ForegroundColor Cyan
& $PyExe -c "import openvino as ov; print('Devices:', ov.Core().available_devices)"

# ---------------------------------------------------------------------------
# 6. Schemalagd aktivitet "CameraAI" (headless server)
# ---------------------------------------------------------------------------
if (-not $NoTask) {
    Write-Host ""
    Write-Host "--- 6/6 Schemalagd aktivitet '$TaskName' ---" -ForegroundColor Cyan
    $PyW = "$AppDir\.venv\Scripts\pythonw.exe"
    $action = New-ScheduledTaskAction -Execute $PyW -Argument "windows\camera_ai_app.py --server" -WorkingDirectory $AppDir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    $settings.RestartCount = 3
    $settings.RestartInterval = (New-TimeSpan -Minutes 1)
    # Säkerställ att SYSTEM kan skriva i app-katalogen
    & icacls $AppDir /grant "SYSTEM:(OI)(CI)M" *> $null
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Camera AI - headless server (0.0.0.0:8000)" -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Aktiviteten '$TaskName' installerad och startad." -ForegroundColor Green
    } catch {
        Write-Host "Kunde inte installera aktiviteten (kräver administratör): $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "--- 6/6 Hoppar över schemalagd aktivitet (-NoTask) ---" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host " Klart! Camera AI är installerat/uppdaterat." -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  - Web/API:    http://<server-ip>:8000"
Write-Host "  - Status:     windows\install-task.ps1 -Status"
Write-Host "  - Logg:       windows\camera_ai.log"
Write-Host "  - Uppdatera:  kör det här scriptet igen."
if (-not $NoTask) {
    Write-Host ""
    Write-Host "OBS: Kontrollera att Ollama körs som Windows-tjänst (standard vid installation),"
    Write-Host "     annars når inte SYSTEM-kontot det. GUI:t nås via http://<server-ip>:8000."
}
