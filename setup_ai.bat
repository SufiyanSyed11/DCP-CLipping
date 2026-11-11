@echo off
cd /d "%~dp0"
echo === Installing the local AI B-roll picker (large download, a few GB) ===
if not exist .venv (echo Run setup.bat first. & pause & exit /b 1)
.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 || .venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 || .venv\Scripts\python -m pip install torch torchvision
.venv\Scripts\python -m pip install -r requirements-ai.txt
.venv\Scripts\python -c "import torch;print('GPU ready:', torch.cuda.is_available())"
pause
