@echo off
REM One-time setup + launch for the Website Tracking Checker MVP (Windows).
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt

echo Installing Chromium for Playwright (first run only)...
python -m playwright install chromium

echo Starting server on http://localhost:8000 ...
uvicorn app:app --host 127.0.0.1 --port 8000
