#!/bin/zsh
set -euo pipefail

ROOT_DIR="${0:A:h}"
cd "$ROOT_DIR"

print "🚀 Setting up OmniStudy AI"

if ! command -v python3 >/dev/null 2>&1; then
  print -u2 "Python 3 is required. Install Python 3.11 or newer and rerun this script."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m playwright install chromium

if [[ ! -f .env ]]; then
  cp .env.example .env
  print "Created .env from .env.example. Add provider credentials before generating content."
fi

if command -v npm >/dev/null 2>&1; then
  npm --prefix frontend install
else
  print -u2 "npm is required for the frontend. Install Node.js 18+ and run: npm --prefix frontend install"
  exit 1
fi

print "✅ Setup complete. Start the backend and frontend using the commands in README.md."
