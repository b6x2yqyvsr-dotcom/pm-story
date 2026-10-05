@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo   第一次要先装依赖…
  call setup.bat || exit /b 1
)
".venv\Scripts\python.exe" app\main.py %*
