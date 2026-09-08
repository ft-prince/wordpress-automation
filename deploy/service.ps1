# Register PressPilot as a Windows service so it survives logout and reboot.
# 1. Download NSSM from https://nssm.cc/download and put nssm.exe on PATH (or next to this script).
# 2. Run as Administrator:  powershell -ExecutionPolicy Bypass -File deploy\service.ps1
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$nssm = if (Get-Command nssm -ErrorAction SilentlyContinue) { "nssm" } else { Join-Path $PSScriptRoot "nssm.exe" }
& $nssm install PressPilot "$root\.venv\Scripts\waitress-serve.exe" "--listen=127.0.0.1:7071 --threads=8 --channel-timeout=600 presspilot.wsgi:application"
& $nssm set PressPilot AppDirectory $root
& $nssm set PressPilot AppEnvironmentExtra PYTHONUNBUFFERED=1
& $nssm set PressPilot AppStdout "$root\service.log"
& $nssm set PressPilot AppStderr "$root\service.log"
& $nssm set PressPilot Start SERVICE_AUTO_START
& $nssm start PressPilot
Write-Host ">> service PressPilot running on http://127.0.0.1:7071  (logs: $root\service.log)"
