@echo off
rem Magic Ball launcher: run.ps1 with execution policy bypass.
rem Keep this file ASCII-only: cmd.exe parses batch files with the OEM codepage.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 (
  echo.
  echo Server stopped with an error. See the messages above.
  pause
)
