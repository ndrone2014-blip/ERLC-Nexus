@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ERLC Nexus - Installer
echo.
echo  ===========================================================
echo    ERLC NEXUS  -  free ERLC CAD / MDT / management platform
echo    Installer
echo  ===========================================================
echo.

rem ---- [1/10] Find Python ------------------------------------------------
echo [1/10] Looking for Python...
set "PY="
for %%V in (3.13 3.12 3) do (
    if not defined PY (
        py -%%V -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo   [FAIL] Python 3.12 or newer was not found.
    echo          Install it from https://www.python.org/downloads/
    echo          and tick "Add python.exe to PATH" during setup, then run install.bat again.
    echo.
    pause
    exit /b 1
)

rem ---- [2/10] Verify version ---------------------------------------------
echo [2/10] Checking Python version...
for /f "delims=" %%I in ('%PY% -c "import platform; print(platform.python_version())"') do set "PYVER=%%I"
echo   [ OK ] Python %PYVER%  (%PY%)

rem ---- [3/10] Virtual environment ----------------------------------------
echo [3/10] Creating virtual environment (.venv)...
if exist ".venv\Scripts\python.exe" (
    echo   [ OK ] Existing .venv found
) else (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [FAIL] Could not create the virtual environment.
        pause
        exit /b 1
    )
    echo   [ OK ] .venv created
)
set "VPY=%~dp0.venv\Scripts\python.exe"

rem ---- [4/10] Dependencies -----------------------------------------------
echo [4/10] Installing dependencies (this can take a few minutes)...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo   [FAIL] Dependency installation failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo   [ OK ] Dependencies installed

rem ---- [5-10/10] Folders, config, database, migrations, checks ----------
"%VPY%" scripts\setup.py
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo  Installation complete. Edit config.env, then double-click start.bat
) else (
    echo  Installation finished with errors - see the messages above.
)
echo.
pause
exit /b %RESULT%
