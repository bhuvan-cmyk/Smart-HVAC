@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo No source given; running the still-image sample instead.
  echo To use a phone stream: RUN_DEMO.cmd "http://PHONE_IP:4747/video"
  .venv\Scripts\python.exe main.py --source tests\bus.jpg
) else (
  .venv\Scripts\python.exe main.py --source "%~1" --window
)

pause
