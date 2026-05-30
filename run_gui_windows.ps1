Set-Location $PSScriptRoot
if (!(Test-Path .venv)) { python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not $env:AI_SUITE_DB) { $env:AI_SUITE_DB = './data/open-artifacts.sqlite3' }
if (-not $env:AI_SUITE_HOST) { $env:AI_SUITE_HOST = '127.0.0.1' }
if (-not $env:AI_SUITE_PORT) { $env:AI_SUITE_PORT = '9142' }
uvicorn app.main:app --host $env:AI_SUITE_HOST --port $env:AI_SUITE_PORT
