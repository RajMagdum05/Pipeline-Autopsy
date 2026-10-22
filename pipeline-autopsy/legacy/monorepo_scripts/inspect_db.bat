@echo off
title Pipeline Autopsy - Database Inspector
cd /d "%~dp0"
if exist "autopsy\.venv\Scripts\python.exe" (
    autopsy\.venv\Scripts\python.exe scripts\inspect_databases.py %*
) else (
    python scripts\inspect_databases.py %*
)
