# Windows production server (waitress, single process so the scheduler runs once).
#   powershell -ExecutionPolicy Bypass -File deploy\run.ps1
# Always-on: deploy\autostart.ps1 (Task Scheduler) or deploy\service.ps1 (NSSM).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONUNBUFFERED = "1"
# venv may be called .venv or env
if (-not (Test-Path .\.venv) -and (Test-Path .\env)) { New-Item -ItemType Junction -Path .venv -Target env | Out-Null }
$port = if ($env:PORT) { $env:PORT } else { "7071" }
& .\.venv\Scripts\python.exe manage.py migrate --noinput
& .\.venv\Scripts\waitress-serve.exe --listen="127.0.0.1:$port" --threads=16 --channel-timeout=600 presspilot.wsgi:application 2>&1 | Tee-Object -FilePath service.log -Append
