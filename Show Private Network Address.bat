@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo DreiTrack is not set up yet.
    echo Run Setup DreiTrack.bat first.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" network_info.py
pause
