# Register PressPilot to start with Windows (Task Scheduler, no extra downloads).
# Run ONCE from an Administrator PowerShell, inside the project folder:
#   powershell -ExecutionPolicy Bypass -File deploy\autostart.ps1
# Remove later with:  schtasks /Delete /TN PressPilot /F
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$run = Join-Path $root "deploy\run.ps1"
$cmd = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$run`""
schtasks /Create /F /TN PressPilot /SC ONSTART /RU SYSTEM /RL HIGHEST /TR $cmd | Out-Null
schtasks /Run /TN PressPilot | Out-Null
Start-Sleep -Seconds 5
schtasks /Query /TN PressPilot /FO LIST | Select-String "Status|Task To Run"
Write-Host ">> PressPilot starts with Windows and is running now on http://127.0.0.1:7071"
Write-Host ">> logs: $root\service.log"
