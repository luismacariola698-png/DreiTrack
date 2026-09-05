@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo DreiTrack one-time Windows setup
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
)

echo Installing required packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Running smoke test...
".venv\Scripts\python.exe" smoke_test.py
if errorlevel 1 goto :error

echo.
echo Setup complete.
echo From now on, double-click DreiTrack.vbs to start the application.
echo.
pause
exit /b 0

:error
echo.
echo Setup failed. Review the error above.
echo.
pause
exit /b 1
