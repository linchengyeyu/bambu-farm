@echo off
cd /d "%~dp0"

echo [INFO] Switching to backend directory...
cd backend

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    
    echo [INFO] Installing dependencies...
    venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo [INFO] Starting Bambu Batch Manager...
venv\Scripts\python.exe -m app.main

pause
