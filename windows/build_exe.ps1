# Camera AI - bygg en fristående Windows-exe (PyInstaller).
# Kör på Windows med Python 3.12 (repo klonat, setup.ps1 kört).
# Bygget tar en stund och ger ca 1-2 GB.
#
#   powershell -ExecutionPolicy Bypass -File windows\build_exe.ps1          # onedir (snabb start)
#   powershell -ExecutionPolicy Bypass -File windows\build_exe.ps1 -OneFile # en enda fil
param(
    [switch]$OneFile
)
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot
$Py = "$AppDir\.venv\Scripts\python.exe"

if (-not (Test-Path $Py)) { Write-Host "Kör först: windows\setup.ps1" -ForegroundColor Red; exit 1 }

Write-Host "=== Camera AI - EXE-bygge (PyInstaller) ==="

# 1. Byggberoenden
& $Py -m pip install --upgrade pip
& $Py -m pip install -r "$AppDir\requirements.txt" openvino pywebview pystray pyinstaller

# 2. Generera ikon
Write-Host "Genererar ikon ..."
& $Py -c @"
from PIL import Image, ImageDraw
from pathlib import Path
size = 256
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, size - 8, size - 8), radius=48, fill=(22, 33, 66, 255))
d.ellipse((size//2 - 78, size//2 - 78, size//2 + 78, size//2 + 78), outline=(120, 200, 255, 255), width=16)
d.ellipse((size//2 - 34, size//2 - 34, size//2 + 34, size//2 + 34), fill=(120, 200, 255, 255))
d.rounded_rectangle((size//2 - 42, 42, size//2 + 42, 88), radius=16, fill=(120, 200, 255, 255))
img.save(Path(r"$AppDir\windows\camera_ai.ico"), format="ICO", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print("ikon klar")
"@

# 3. PyInstaller
$Mode = if ($OneFile) { "--onefile" } else { "--onedir" }
$Name = "CameraAI"
Set-Location $AppDir
& $Py -m PyInstaller --noconfirm --clean $Mode `
    --name $Name `
    --icon "windows\camera_ai.ico" `
    --add-data "static;static" `
    --add-data "yolo11n.pt;." `
    --add-data "yolo11s.pt;." `
    --collect-all ultralytics `
    --collect-all openvino `
    --hidden-import "webview" `
    --hidden-import "pystray" `
    "windows\camera_ai_app.py"

Write-Host ""
Write-Host "Klar!" -ForegroundColor Green
if ($OneFile) {
    Write-Host "EXE:  $AppDir\dist\CameraAI.exe"
} else {
    Write-Host "Mapp: $AppDir\dist\CameraAI\CameraAI.exe   (flytta hela mappen)"
}
Write-Host "Kopiera till datorn med Arc B50 Pro och kör CameraAI.exe"
Write-Host "(.env, uploads/, media/ och OpenVINO-modeller skapas automatiskt bredvid exe:n)"
