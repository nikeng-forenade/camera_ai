# Camera AI - bygger MSI + Burn-bundle (WiX 6).
#   powershell -ExecutionPolicy Bypass -File packaging\wix\build-msi.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\wix\build-msi.ps1 -SkipBundle
param([switch]$SkipBundle)
$ErrorActionPreference = "Stop"
$wix = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ""))
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
Set-Location $wix

if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    Write-Host "WiX saknas - installera:  dotnet tool install --global wix" -ForegroundColor Red
    exit 1
}

# 1. nssm.exe (for tjansten)
if (-not (Test-Path "$wix\nssm.exe")) {
    Write-Host "Laddar ner nssm ..."
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$wix\nssm.zip"
    Expand-Archive -Path "$wix\nssm.zip" -DestinationPath "$wix\nssm_tmp" -Force
    Copy-Item "$wix\nssm_tmp\nssm-2.24\win64\nssm.exe" "$wix\nssm.exe" -Force
    Remove-Item "$wix\nssm.zip", "$wix\nssm_tmp" -Recurse -Force -ErrorAction SilentlyContinue
}

# 2. MSI
Write-Host "Bygger CameraAI.msi ..."
wix build "$wix\product.wxs" -o "$wix\CameraAI.msi"
if ($LASTEXITCODE -ne 0) { exit 1 }

if ($SkipBundle) {
    Write-Host "MSI klar: $wix\CameraAI.msi" -ForegroundColor Green
    exit 0
}

# 3. Installatorer for bundlen (Python; Ollama installeras separat - tagits bort ur bundlen)
if (-not (Test-Path "$wix\python-3.12.7-amd64.exe")) {
    Write-Host "Laddar ner Python 3.12.7 (stor fil, tar en stund) ..."
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile "$wix\python-3.12.7-amd64.exe"
}

# 3b. Bal-extension for bundlen (WixStandardBootstrapperApplication / UI)
$BalDll = "$wix\bal\wixext6\WixToolset.BootstrapperApplications.wixext.dll"
if (-not (Test-Path $BalDll)) {
    Write-Host "Laddar ner WixToolset.Bal.wixext (for bootstrapper-UI) ..."
    Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/wixtoolset.bal.wixext/6.0.2/wixtoolset.bal.wixext.6.0.2.nupkg" -OutFile "$wix\bal.nupkg"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory("$wix\bal.nupkg", "$wix\bal")
    Remove-Item "$wix\bal.nupkg" -Force
}
if (-not (Test-Path $BalDll)) {
    # kanske annan s\u00f6kv\u00e4g i paketet
    $BalDll = (Get-ChildItem "$wix\bal" -Recurse -Filter "*.wixext.dll" | Select-Object -First 1).FullName
}

# 3c. Util-extension (for util:RegistrySearch i bundlen)
$UtilDll = "$wix\util\wixext6\WixToolset.Util.wixext.dll"
if (-not (Test-Path $UtilDll)) {
    Write-Host "Laddar ner WixToolset.Util.wixext ..."
    Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/wixtoolset.util.wixext/6.0.2/wixtoolset.util.wixext.6.0.2.nupkg" -OutFile "$wix\util.nupkg"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory("$wix\util.nupkg", "$wix\util")
    Remove-Item "$wix\util.nupkg" -Force
}
if (-not (Test-Path $UtilDll)) {
    $UtilDll = (Get-ChildItem "$wix\util" -Recurse -Filter "*.wixext.dll" | Select-Object -First 1).FullName
}

# 4. Burn-bundle
Write-Host "Bygger CameraAI-Setup.exe (Burn-bundle) ..."
wix build "$wix\bundle.wxs" -o "$repo\dist\CameraAI-Setup.exe" -ext "$BalDll" -ext "$UtilDll"
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ""
Write-Host ("Klar!  MSI:    " + $wix + "\CameraAI.msi") -ForegroundColor Green
Write-Host ("       Bundle: dist\CameraAI-Setup.exe") -ForegroundColor Green
