#!/usr/bin/env bash
# One-time setup + launch for the Website Tracking Checker MVP.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo "Installing Chromium for Playwright (first run only)..."
python -m playwright install --with-deps chromium || python -m playwright install chromium

echo "Starting server on http://localhost:8000 ..."
exec uvicorn app:app --host 127.0.0.1 --port 8000
