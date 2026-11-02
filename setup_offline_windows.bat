@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (py -3 -m venv .venv)
.venv\Scripts\python.exe -m pip install -r requirements-offline.txt
if errorlevel 1 (echo Offline installation failed. See README. & pause & exit /b 1)
echo Offline Piper engine installed. Download voices in Voice Studio to use them without internet.
pause
