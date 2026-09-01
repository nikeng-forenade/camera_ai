# Camera AI - setup Ollama for Intel Arc B50 Pro (Vulkan) + pull moondream.
# Kor som admin (satter OLLAMA_VULKAN=1 globalt):
#   powershell -ExecutionPolicy Bypass -File windows\setup-ollama.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== Camera AI - Ollama setup (Arc B50 Pro / Vulkan) ===" -ForegroundColor Cyan

# 1. Saknas Ollama? Installera via winget
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama saknas - installerar via winget ..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Host "Ollama installerat. Starta om PowerShell och kor scriptet igen." -ForegroundColor Yellow
        exit 0
    }
}
Write-Host ("Ollama: " + (ollama --version)) -ForegroundColor Green

# 2. Satt OLLAMA_VULKAN=1 (globalt om admin)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "Machine")
    Write-Host "OLLAMA_VULKAN=1 satt (Machine)." -ForegroundColor Green
} else {
    Write-Host "Kor som ADMIN for att satta OLLAMA_VULKAN=1 globalt." -ForegroundColor Yellow
}
$env:OLLAMA_VULKAN = "1"   # for denna session (arvs av nyprocesstartade processer)

# 3. Starta om Ollama sa Vulkan tas emot
Write-Host "Startar om Ollama ..."
Get-Process | Where-Object { $_.ProcessName -like "ollama*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Process -FilePath (Get-Command ollama).Source -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3

# 4. Ladda ner moondream (hoppa över om den redan finns)
$models = & ollama list 2>$null
if ($LASTEXITCODE -eq 0 -and $models -match "moondream") {
    Write-Host "moondream finns redan - hoppar över nedladdning." -ForegroundColor Green
} else {
    Write-Host "Laddar ner moondream ... (kan ta en stund)"
    $ErrorActionPreference = "Continue"
    ollama pull moondream 2>&1 | Out-Host
    $ErrorActionPreference = "Stop"
}

# 5. Klart + verifiering
Write-Host ""
Write-Host "=== Klar! ===" -ForegroundColor Green
ollama list
Write-Host ""
Write-Host "Testa:  ollama run moondream"
Write-Host "Se i Aktivitetshanteraren (GPU) att Arc B50 Pro belastas = Vulkan funkar."
