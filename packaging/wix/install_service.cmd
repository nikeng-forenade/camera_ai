@echo off
rem Camera AI - installera beroenden + registrera tjansten (kors av MSI:n).
rem Finner Python dynamiskt (py-launchern) sa tjänsten pekar pa ratt sökvag.
setlocal
set INSTALLDIR=%~dp0
if "%INSTALLDIR:~-1%"=="\" set INSTALLDIR=%INSTALLDIR:~0,-1%

rem 1) Hitta python.exe via py-launchern (fallback: standard sökvag)
set PYEXE=
for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys;print(sys.executable)" 2^>nul`) do set PYEXE=%%P
if not defined PYEXE if exist "%ProgramFiles%\Python312\python.exe" set PYEXE=%ProgramFiles%\Python312\python.exe
if not defined PYEXE if exist "%ProgramFiles%\Python\Python312\python.exe" set PYEXE=%ProgramFiles%\Python\Python312\python.exe
if not defined PYEXE (
  echo Kunde inte hitta Python 3.12
  exit /b 1
)

rem 2) Härled pythonw.exe fran samma mapp
for %%D in ("%PYEXE%") do set PYDIR=%%~dpD
set PYW=%PYDIR%pythonw.exe

echo Python: %PYEXE%

rem 3) Installera beroenden (fastapi, ultralytics, openvino, ...)
"%PYEXE%" -m pip install --no-cache-dir -r "%INSTALLDIR%\requirements.txt" openvino

rem 4) Registrera + starta tjänsten (tar bort ev. gammal tjänst forst)
"%INSTALLDIR%\nssm.exe" stop CameraAI >nul 2>&1
"%INSTALLDIR%\nssm.exe" remove CameraAI confirm >nul 2>&1
"%INSTALLDIR%\nssm.exe" install CameraAI "%PYW%" "%INSTALLDIR%\windows\camera_ai_app.py" --server
"%INSTALLDIR%\nssm.exe" set CameraAI AppDirectory "%INSTALLDIR%"
"%INSTALLDIR%\nssm.exe" set CameraAI AppStdout "%INSTALLDIR%\camera_ai.log"
"%INSTALLDIR%\nssm.exe" set CameraAI AppStderr "%INSTALLDIR%\camera_ai.log"
"%INSTALLDIR%\nssm.exe" set CameraAI Start SERVICE_AUTO_START
"%INSTALLDIR%\nssm.exe" start CameraAI

exit /b 0
