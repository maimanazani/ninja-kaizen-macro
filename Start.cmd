@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
if not exist ".venv\installed" (
  ".venv\Scripts\python.exe" -m pip install pillow opencv-python-headless
  if errorlevel 1 goto failed
  echo ready>".venv\installed"
)
".venv\Scripts\python.exe" farm.py
if errorlevel 1 pause
exit /b
:failed
echo Setup failed. Make sure Python 3 is installed and available as python.
pause
exit /b 1


