# Deploying PressPilot behind a Cloudflare Tunnel

Everything runs in one process on one machine: Django + the dashboard + the scheduler.
The tunnel is the only thing exposed; nothing listens on a public port.

## 1. Machine

Linux (Ubuntu/Debian recommended) or macOS with Python 3.11+ and Node 18+. Windows works with `deploy/run.ps1`.

```bash
git clone https://github.com/ft-prince/wordpress-automation.git /opt/presspilot
cd /opt/presspilot
deploy/install.sh          # venv, deps, dashboard build, migrations
nano .env                  # GROQ_KEY, PUBLIC_URL=https://press.example.com
deploy/run.sh              # gunicorn on 127.0.0.1:7071
```

Always-on: `sudo cp deploy/presspilot.service /etc/systemd/system/`, fix `User=` and paths, `sudo systemctl enable --now presspilot`.
Updates: `git pull && deploy/install.sh && sudo systemctl restart presspilot`.

## 2. Tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create presspilot
cloudflared tunnel route dns presspilot press.example.com
cp deploy/cloudflared.yml ~/.cloudflared/config.yml   # set hostname + credentials-file
sudo cloudflared service install
```

Strongly recommended: put **Cloudflare Access** (Zero Trust → Applications) in front of the hostname so only allowed emails reach the login page at all. The app has its own login and a per-IP throttle, but Access keeps bots away entirely.

## 3. First visit

Open `https://press.example.com`. The first account created is the admin. Then: Sites → connect WordPress; Secrets → keys; SEO → Crawl. The Guide page inside the app covers the rest.

## 4. Google (Search Console + GA4)

The OAuth redirect URI must be exactly `https://press.example.com/api/google/callback` (from `PUBLIC_URL`). Add it in Google Cloud → Auth Platform → Clients → your web client. Then Sites → Connect Google.

## 5. What to back up

`automation.db` (all data), `.env` (keys, Google token), `sites.json` (WordPress credentials), `registry/` (job definitions), `.backups/`.

## 6. Ports and processes

| What | Where |
|---|---|
| Dashboard + API | gunicorn, 127.0.0.1:7071, 1 worker × 8 threads |
| Scheduler | inside that worker (APScheduler); one worker so it runs once |
| Jobs | subprocesses of the worker (`.venv/bin/python <script>`), logs in SQLite |
| Tunnel | cloudflared → 127.0.0.1:7071 |
