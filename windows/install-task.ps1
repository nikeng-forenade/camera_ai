# Camera AI - installera som schemalagd aktivitet (Task Scheduler), headless server.
#
# Enklaste sättet att köra Camera AI dygnet runt på en server utan extra
# beroenden (NSSM behövs inte). Registrerar aktiviteten "CameraAI" som
# startar webbservern (windows\camera_ai_app.py --server) vid start av
# datorn. Körs som SYSTEM (utan inloggning), startar om automatiskt vid
# fel och loggar till windows\camera_ai.log.
#
#   powershell -ExecutionPolicy Bypass -File windows\install-task.ps1
#
# Alternativ:
#   -Uninstall      Ta bort aktiviteten (stoppar även körande process)
#   -Status         Visa status + senaste logg
#   -Start          Starta aktiviteten direkt (utan att vänta på trigger)
#   -Stop           Stoppa aktiviteten
#   -RunAsUser      Kör som aktuell användare vid inloggning istället för
#                   SYSTEM vid start (användbart om Ollama bara körs som
#                   användare och inte som Windows-tjänst)
#   -NoAutoRestart  Inaktivera automatisk omstart vid fel
#   -UseExe         Använd byggd exe (dist\CameraAI\CameraAI.exe --server)
#                   istället för .venv-python
param(
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$Start,
    [switch]$Stop,
    [switch]$RunAsUser,
    [switch]$NoAutoRestart,
    [switch]$UseExe,
    [string]$TaskName = "CameraAI"
)
$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $AppDir "windows\camera_ai.log"

# Skydda mot att registrera aktiviteten från fel mapp (enhetsrot / Windows-mappen
# / hem-/skrivbordsmappen). Aktiviteten måste peka på en riktig app-mapp.
$ProfileRoot = [Environment]::GetFolderPath("UserProfile")
$badLocations = @(
    ([System.IO.Path]::GetPathRoot($AppDir) -eq $AppDir),
    ($AppDir -eq $env:SystemRoot),
    ($AppDir.StartsWith($env:SystemRoot + "\")),
    ($AppDir -eq $ProfileRoot),
    ($AppDir -eq (Join-Path $ProfileRoot "Desktop")),
    ($AppDir -eq (Join-Path $ProfileRoot "Documents"))
)
$badReason = @("enhetsroten", "Windows-mappen", "något under Windows-mappen", "hemkatalogen", "skrivbordsmappen", "dokumentmappen")
$badIdx = [Array]::IndexOf($badLocations, $true)
if ($badIdx -ge 0) {
    Write-Host "ERROR: Registrera aktiviteten från app-mappen, t.ex. C:\camera_ai - inte från enhetsroten, Windows-mappen eller hem-/skrivbordsmappen." -ForegroundColor Red
    Write-Host "  Detekterad mapp: '$AppDir'  (matchar: $($badReason[$badIdx]))" -ForegroundColor Yellow
    exit 1
}

# ---- Visa status ---------------------------------------------------------
function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Ingen aktivitet '$TaskName' finns. Installera med:" -ForegroundColor Yellow
        Write-Host "  powershell -ExecutionPolicy Bypass -File windows\install-task.ps1"
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "=== Aktivitet: $TaskName ===" -ForegroundColor Cyan
    Write-Host "Status:            $($task.State)"
    Write-Host "Senast körning:    $($info.LastRunTime)  (resultat 0x$('{0:X8}' -f $info.LastTaskResult))"
    Write-Host "Nästa körning:     $($info.NextRunTime)"
    Write-Host "Kör som:           $($task.Principal.UserId)"
    if (Test-Path $LogFile) {
        Write-Host ""
        Write-Host "--- Senaste logg ($LogFile) ---"
        Get-Content $LogFile -Tail 15
    }
}

# ---- Hantera flaggor -----------------------------------------------------
if ($Status) { Show-Status; exit 0 }
if ($Stop) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "Aktiviteten '$TaskName' stoppad." -ForegroundColor Green
    exit 0
}
if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Aktiviteten '$TaskName' startad. Status via: -Status" -ForegroundColor Green
    exit 0
}
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='CameraAI.exe'" |
        Where-Object { $_.CommandLine -match "camera_ai_app\.py|--server" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Aktiviteten '$TaskName' borttagen." -ForegroundColor Green
    exit 0
}

# ---- Förbered körkommando ------------------------------------------------
if ($UseExe) {
    $Exe = Join-Path $AppDir "dist\CameraAI\CameraAI.exe"
    if (-not (Test-Path $Exe)) { Write-Host "Hittar inte $Exe - bygg först med windows\build_exe.ps1" -ForegroundColor Red; exit 1 }
    $Program = $Exe
    $Arguments = "--server"
    Write-Host "Använder byggd exe: $Exe" -ForegroundColor Cyan
} else {
    $PyW = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $PyW)) { Write-Host "Kör först: windows\setup.ps1 (saknar .venv)" -ForegroundColor Red; exit 1 }
    $Program = $PyW
    $Arguments = "windows\camera_ai_app.py --server"
    Write-Host "Använder .venv: $PyW" -ForegroundColor Cyan
}

# ---- Skapa aktiviteten ---------------------------------------------------
Write-Host ""
Write-Host "=== Installerar '$TaskName' som schemalagd aktivitet ==="
Write-Host "App-katalog: $AppDir"

$action = New-ScheduledTaskAction -Execute $Program -Argument $Arguments -WorkingDirectory $AppDir

if ($RunAsUser) {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
    Write-Host "Kör som: $env:USERNAME vid inloggning (användaren måste vara inloggad)."
} else {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Write-Host "Kör som: SYSTEM vid start av datorn (ingen inloggning krävs)."
    # Säkerställ att SYSTEM kan skriva i app-katalogen (uploads/, media/, .env, loggar)
    & icacls $AppDir /grant "SYSTEM:(OI)(CI)M" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Varning: kunde inte ge SYSTEM skrivrätt i $AppDir" -ForegroundColor Yellow
    }
}

if (-not $NoAutoRestart) {
    # Obs: RestartCount/RestartInterval MÅSTE skickas till New-ScheduledTaskSettingsSet,
    # annars serialiseras intervallet felaktigt (00:01:00 istället för PT1M) och Task Scheduler avvisar XML:n.
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Write-Host "Automatisk omstart vid fel: 3 försök / 1 min."
} else {
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    Write-Host "Automatisk omstart vid fel: av."
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Camera AI - headless server (0.0.0.0:8000)" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Klart! '$TaskName' är installerad och startad." -ForegroundColor Green
Write-Host "  - GUI/API:  http://<server-ip>:8000"
Write-Host "  - Status:   windows\install-task.ps1 -Status"
Write-Host "  - Logg:     windows\camera_ai.log"
Write-Host "  - Ta bort:  windows\install-task.ps1 -Uninstall"
if ($RunAsUser) {
    Write-Host "OBS: Eftersom aktiviteten körs som användare måste denne vara inloggad." -ForegroundColor Yellow
} else {
    Write-Host "OBS: Kontrollera att Ollama körs som Windows-tjänst (standard vid installation),"
    Write-Host "     annars når inte SYSTEM-kontot det. GUI:t nås via http://<server-ip>:8000."
}
