@echo off
cd /d "%~dp0"
echo Starting WebRunner...
python main.py
if errorlevel 1 (
    echo.
    echo Failed to start. Make sure Python is installed.
    pause
)
