# Windows production server (waitress, single process so the scheduler runs once).
#   powershell -ExecutionPolicy Bypass -File deploy\run.ps1
# Always-on: deploy\autostart.ps1 (Task Scheduler) or deploy\service.ps1 (NSSM).
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
$env:PYTHONUNBUFFERED = "1"
# venv may be called .venv or env
$py = if (Test-Path .\.venv\Scripts\python.exe) { ".\.venv\Scripts" } elseif (Test-Path .\env\Scripts\python.exe) { ".\env\Scripts" } else { throw "no virtualenv found - run deploy\install.ps1 first" }
$port = if ($env:PORT) { $env:PORT } else { "7071" }
"$(Get-Date -Format s) starting on 127.0.0.1:$port (venv $py)" | Out-File -Append -FilePath "$root\service.log"
& "$py\python.exe" manage.py migrate --noinput 2>&1 | Out-File -Append -FilePath "$root\service.log"
# waitress logs to stderr; hand the redirection to cmd so PowerShell never sees it as an error
cmd /c "`"$py\waitress-serve.exe`" --listen=127.0.0.1:$port --threads=16 --channel-timeout=600 presspilot.wsgi:application >> `"$root\service.log`" 2>&1"
