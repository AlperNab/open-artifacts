#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
export AI_SUITE_DB=${AI_SUITE_DB:-./data/open-artifacts.sqlite3}
uvicorn app.main:app --host ${AI_SUITE_HOST:-127.0.0.1} --port ${AI_SUITE_PORT:-9142}
