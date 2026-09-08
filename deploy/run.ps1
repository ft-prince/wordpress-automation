# Windows: run from the repo root in PowerShell. gunicorn needs Unix; use Django's server.
# For always-on, register with NSSM (nssm install presspilot) pointing at this script.
$env:PYTHONUNBUFFERED = "1"
& .\.venv\Scripts\python.exe manage.py migrate --noinput
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:7071 --noreload
