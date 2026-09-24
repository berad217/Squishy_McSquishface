@echo off
title Squishy McSquishface
cd /d "%~dp0"

rem Prefer the py launcher (python.org installs); fall back to python on PATH.
rem The Microsoft Store "python" stub fails the --version check, so it is skipped.
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    echo.
    echo Squishy needs Python 3.11 or newer, and it isn't installed.
    echo Get it from https://www.python.org/downloads/ - tick "Add python.exe to PATH" -
    echo then double-click Squishy.bat again. README.md has the details.
    echo.
    pause
    exit /b 1
)

%PY% launch.py %*
if errorlevel 1 pause
