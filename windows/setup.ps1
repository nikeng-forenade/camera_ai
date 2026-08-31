# Camera AI - Windows-app setup (Intel Arc B50 Pro + Vulkan + GUI)
# Kör en gång efter clone. Kräver Python 3.12 (x64) och Git:
#   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
param(
    [string]$Python = "py"   # py launcher; override om det behövs
)
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot

Write-Host "=== Camera AI - Windows setup ===" -ForegroundColor Cyan
Write-Host "App dir: $AppDir"

# 1. Python-venv
$Launcher = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
if (-not (Test-Path "$AppDir\.venv")) {
    Write-Host "Creating .venv ..."
    if ($Launcher -eq "py") { & py -3.12 -m venv "$AppDir\.venv" } else { & python -m venv "$AppDir\.venv" }
}
$Py = "$AppDir\.venv\Scripts\python.exe"

# 2. Beroenden (openvino = Arc GPU, pywebview = fönster, pystray = tray-ikon)
& $Py -m pip install --upgrade pip
& $Py -m pip install -r "$AppDir\requirements.txt" openvino pywebview pystray

# 3. .env med Arc B50 Pro + lokal Ollama
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
    Write-Host "Wrote .env (YOLO_DEVICE=openvino:GPU)." -ForegroundColor Green
} else {
    Write-Host ".env finns redan - kontrollera YOLO_DEVICE=openvino:GPU."
}

# 4. Ollama + Vulkan (Arc B50 Pro)
Write-Host ""
Write-Host "--- Ollama + Intel Arc B50 Pro (Vulkan) ---"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama hittad. Aktivera Vulkan-backend för Arc-kortet:"
    Write-Host "  1. Systemvariabel:  OLLAMA_VULKAN=1"
    Write-Host "  2. Starta om Ollama (Settings -> Quit, eller tjänsten)."
    Write-Host "  3. Test:  ollama run moondream  (Arc-kortet ska belastas i Task Manager)"
} else {
    Write-Host "Ollama saknas - installera https://ollama.com och kör sedan: ollama pull moondream"
}

# 5. Verifiera att OpenVINO ser Arc-kortet
Write-Host ""
Write-Host "--- OpenVINO enheter (Arc B50 Pro ska synas) ---"
& $Py -c "import openvino as ov; print('Devices:', ov.Core().available_devices)"

Write-Host ""
Write-Host "Starta appen med:  .\windows\start.bat   (GUI-fönster + taskbar-ikon)"
