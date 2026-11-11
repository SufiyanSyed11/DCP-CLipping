@echo off
cd /d "%~dp0"
if not exist .venv (echo Run setup.bat first. & pause & exit /b 1)
.venv\Scripts\python -m yt_dlp -U >nul 2>nul
.venv\Scripts\python -m dcp.app
pause
