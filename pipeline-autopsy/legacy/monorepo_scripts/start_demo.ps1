# Pipeline Autopsy - PowerShell Demo Launcher
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  PIPELINE AUTOPSY - ONE-CLICK DEMO LAUNCHER" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan

Set-Location $PSScriptRoot

if (Test-Path "autopsy\.venv\Scripts\python.exe") {
    & "autopsy\.venv\Scripts\python.exe" "scripts\launch_demo.py"
} else {
    python "scripts\launch_demo.py"
}
