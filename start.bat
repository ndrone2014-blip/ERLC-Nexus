@echo off
setlocal
cd /d "%~dp0"
title ERLC Nexus
if not exist ".venv\Scripts\python.exe" (
    echo [FAIL] ERLC Nexus is not installed yet. Run install.bat first.
    pause
    exit /b 1
)
rem Usage: start.bat          website + Discord bot
rem        start.bat web      website only
rem        start.bat bot      Discord bot only
".venv\Scripts\python.exe" run.py %*
echo.
pause
