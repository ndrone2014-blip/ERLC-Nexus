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

## Public link from your own PC (start-online)

`start-online.bat` / `./start-online.sh` (`run.py online`) runs Cloudflare Tunnel next to
ERLC Nexus. The website keeps listening on `127.0.0.1`; `cloudflared` makes an outbound
connection to Cloudflare, which serves your site over HTTPS. For that run only, the launcher sets
`PUBLIC_URL`, `DISCORD_REDIRECT_URI`, `COOKIE_SECURE=true`, `TRUST_PROXY=true` and
`DEV_LOGIN=false` (config.env is not modified). If the tunnel drops, it is reconnected; if the
address changes, the website and bot restart so links stay correct. Logs: `data/logs/tunnel.log`.

`cloudflared` (Cloudflare's official open-source client) is found via `CLOUDFLARED_PATH`,
`data/tools`, or your `PATH`; otherwise it is downloaded once from Cloudflare's GitHub releases.
On macOS install it with `brew install cloudflared`.

Quick tunnels are meant for testing: Cloudflare gives no uptime guarantee and the address changes
on every start.

### A permanent link

A fixed address needs a domain you own (domains usually cost money — about $10/year) added to a
free Cloudflare account:

1. Cloudflare dashboard → **Zero Trust → Networks → Tunnels → Create a tunnel** (Cloudflared).
2. Copy the **token** from the install command it shows.
3. **Public hostname**: e.g. `cad.yourdomain.com` → Service `HTTP` → `127.0.0.1:8420`.
4. In `config.env`:
   ```
   TUNNEL_TOKEN=<the token>
   PUBLIC_URL=https://cad.yourdomain.com
   ```
5. Add `https://cad.yourdomain.com/auth/callback` to Discord OAuth2 Redirects **once**.
6. Run `start-online.bat`. The address now stays the same.

`TUNNEL_TOKEN` is a secret: it's masked in status pages, passed to `cloudflared` through the
environment (not the command line) and scrubbed from the tunnel log.

## Making the website reachable

By default the website only listens on `127.0.0.1` (this computer). To open it to others:

* **Local network only:** set `WEB_HOST=0.0.0.0`, allow port 8420 in the firewall, and use
  `http://<pc-ip>:8420`. Add that callback URL in the Discord Developer Portal and set
  `PUBLIC_URL=http://<pc-ip>:8420`.
* **Internet:** use `start-online` (above), or put ERLC Nexus behind a reverse proxy with HTTPS.
  Keep `WEB_HOST=127.0.0.1` and let the proxy forward to it. With a proxy on the same computer,
  set `TRUST_PROXY=true` so logins, rate limits and the audit log see visitors' real IP addresses.

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
TRUST_PROXY=true
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
