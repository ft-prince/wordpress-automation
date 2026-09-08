# Windows install / update. Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File deploy\install.ps1
# Needs: Python 3.11+ (python.org, "Add to PATH" ticked), Node 18+ (nodejs.org), Git.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python not found - install Python 3.11+ and tick 'Add to PATH'" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm not found - install Node 18+ from nodejs.org" }

if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host ">> created .env from .env.example - fill in GROQ_KEY and PUBLIC_URL" }

Push-Location dashboard
npm ci --silent
npm run build --silent
Pop-Location

& .\.venv\Scripts\python.exe manage.py migrate --noinput
Write-Host ">> installed. Start with: powershell -ExecutionPolicy Bypass -File deploy\run.ps1"
Write-Host ">> first visit to the dashboard creates the admin account"
