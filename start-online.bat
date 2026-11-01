@echo off
setlocal
cd /d "%~dp0"
title ERLC Nexus (online)
if not exist ".venv\Scripts\python.exe" (
    echo [FAIL] ERLC Nexus is not installed yet. Run install.bat first.
    pause
    exit /b 1
)
rem Starts the website + Discord bot and gives the website a public https:// link
rem through Cloudflare Tunnel (free, no router changes). Stop with Ctrl+C or stop.bat.
".venv\Scripts\python.exe" run.py online
echo.
pause
