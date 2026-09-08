#!/usr/bin/env bash
# One-shot install on a fresh Linux/macOS box. Re-runnable (pulls, rebuilds, migrates).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null || { echo "python3 (3.11+) is required"; exit 1; }
command -v npm >/dev/null || { echo "node + npm are required (for the dashboard build)"; exit 1; }

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo ">> created .env from .env.example - fill in GROQ_KEY and PUBLIC_URL"; }

(cd dashboard && npm ci --silent && npm run build --silent)

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check --deploy 2>/dev/null | grep -v "^$" || true
echo ">> installed. Start with: deploy/run.sh   (or install deploy/presspilot.service)"
echo ">> first visit creates the admin account; every later user is made on the Secrets page"
