@echo off
rem Camera AI - Windows desktop app (GUI window + taskbar/tray icon).
rem Starts the server and opens a native pywebview window (browser fallback).
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo .venv missing - run windows\setup.ps1 first.
  pause
  exit /b 1
)
start "Camera AI" ".venv\Scripts\pythonw.exe" "windows\camera_ai_app.py"
