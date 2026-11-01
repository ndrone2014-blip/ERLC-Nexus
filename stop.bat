@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo ERLC Nexus is not installed.
    exit /b 1
)
".venv\Scripts\python.exe" run.py stop
timeout /t 3 >nul
