@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Creating local Python environment...
    py -3 -m venv .venv
    if errorlevel 1 (echo Python 3 is required. & pause & exit /b 1)
)
REM Only install packages when they are not already installed (works on later offline launches).
.venv\Scripts\python.exe -c "import fastapi, uvicorn, edge_tts" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (echo Dependency installation failed. & pause & exit /b 1)
)
echo Open http://127.0.0.1:8765
start "" "http://127.0.0.1:8765"
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765
pause
