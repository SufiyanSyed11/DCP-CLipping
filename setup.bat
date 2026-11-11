@echo off
cd /d "%~dp0"
echo === DCP Clipper setup ===
where python >nul 2>nul || (echo Python was not found. Install Python 3.11+ from python.org and tick "Add to PATH". & pause & exit /b 1)
where ffmpeg >nul 2>nul || (echo FFmpeg was not found on PATH. Install it first. & pause & exit /b 1)
python -m venv .venv || (pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
if not exist assets\bgm_under.mp3 if exist "D:\YT SHORTS\brolls\_pipeline\bgm_under.mp3" copy "D:\YT SHORTS\brolls\_pipeline\bgm_under.mp3" assets\bgm_under.mp3
if not exist config.json copy config.example.json config.json
echo.
echo Done. Double-click run.bat to start. (Optional: setup_ai.bat adds the automatic B-roll picker.)
pause
