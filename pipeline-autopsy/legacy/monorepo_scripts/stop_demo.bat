@echo off
title Stop Pipeline Autopsy Application
cls
cd /d "%~dp0"
if exist "autopsy\.venv\Scripts\python.exe" (
    autopsy\.venv\Scripts\python.exe scripts\stop_demo.py
) else (
    python scripts\stop_demo.py
)
echo.
echo Application and background services stopped.
pause
