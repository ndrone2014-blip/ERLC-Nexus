# Optional deployment guide

ERLC Nexus is designed to run on your own Windows PC for free. This guide is only for
people who **choose** to run it elsewhere. Third-party hosting, domain names and
certificates may cost money and are not provided or guaranteed by this project.

## Keeping it online

ERLC Nexus is only available while its host machine is on, awake and the launcher window
is open. Options:

* **Same PC, longer uptime:** disable sleep in Windows power settings while you host.
* **Another always-on computer** (old PC, mini PC, home server): install as usual.
* **A Linux server/VPS:** use `install.sh` and `start.sh` (below).

## Linux / macOS

```bash
git clone https://github.com/ndrone2014-blip/ERLC-Nexus.git
cd ERLC-Nexus
./install.sh          # Python 3.12+ required
nano config.env       # fill in settings
./start.sh            # or: ./start.sh web  /  ./start.sh bot
./stop.sh
```

### systemd service (example)

```ini
# /etc/systemd/system/erlc-nexus.service
[Unit]
Description=ERLC Nexus
After=network-online.target

[Service]
WorkingDirectory=/opt/ERLC-Nexus
ExecStart=/opt/ERLC-Nexus/.venv/bin/python run.py
ExecStop=/opt/ERLC-Nexus/.venv/bin/python run.py stop
Restart=on-failure
User=nexus

[Install]
WantedBy=multi-user.target
```

## Making the website reachable

By default the website only listens on `127.0.0.1` (this computer). To open it to others:

* **Local network only:** set `WEB_HOST=0.0.0.0`, allow port 8420 in the firewall, and use
  `http://<pc-ip>:8420`. Add that callback URL in the Discord Developer Portal and set
  `PUBLIC_URL=http://<pc-ip>:8420`.
* **Internet:** put ERLC Nexus behind a reverse proxy with HTTPS. Keep `WEB_HOST=127.0.0.1`
  and let the proxy forward to it.

### Reverse proxy example (Caddy, automatic HTTPS)

```
cad.example.com {
    reverse_proxy 127.0.0.1:8420
}
```

Then in `config.env`:

```
PUBLIC_URL=https://cad.example.com
COOKIE_SECURE=true
```

and add `https://cad.example.com/auth/callback` to your Discord OAuth2 redirects.
WebSockets (`/ws`) must be proxied too (Caddy and most modern proxies do this automatically).

## PostgreSQL (larger communities)

SQLite handles typical community sizes well. For very large communities:

1. `pip install asyncpg` inside the virtual environment.
2. Set `DATABASE_URL=postgresql+asyncpg://user:password@host:5432/nexus`.
3. Run `install.bat` / `install.sh` (creates the schema via migrations).

PostgreSQL support is built into the data layer (SQLAlchemy + Alembic, partial indexes for
both engines) but has not been tested by the project yet — see TEST_REPORT.md.

## ERLC event webhooks

If your site is reachable over public HTTPS you can set `ERLC_WEBHOOK_ENABLED=true` and
enter `https://your-domain/api/erlc/webhook` in the private server's Event Webhook setting.
Requests are verified with the official Ed25519 key. Polling remains the data source for
emergency calls (per the official docs, webhooks don't replace polling).
