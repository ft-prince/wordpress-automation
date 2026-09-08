#!/usr/bin/env bash
# Production server. ONE worker on purpose: the scheduler lives in-process and must run once.
# Threads handle the dashboard's parallel polling; jobs run as subprocesses anyway.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-7071}"
exec .venv/bin/gunicorn presspilot.wsgi:application \
  --bind "127.0.0.1:${PORT}" --workers 1 --threads 8 --timeout 600 \
  --access-logfile - --error-logfile - --capture-output
