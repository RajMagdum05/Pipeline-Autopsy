@echo off
title Pipeline Autopsy Application Launcher
cls
echo ======================================================================
echo   PIPELINE AUTOPSY - APPLICATION LAUNCHER
echo ======================================================================
cd /d "%~dp0"
if exist "autopsy\.venv\Scripts\python.exe" (
    autopsy\.venv\Scripts\python.exe scripts\launch_demo.py
) else (
    python scripts\launch_demo.py
)
if errorlevel 1 (
    echo.
    echo Launcher encountered an error. Press any key to exit.
    pause
)
