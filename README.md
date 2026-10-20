# SpecterGate

A self-hosted control panel for proxy users, subscriptions, nodes and DNS tunnels.

SpecterGate combines a React interface with a FastAPI backend and Xray-core. It supports individual and shared subscriptions, administrator scopes, per-user resource permissions and traffic quotas.

## Features

- VLESS, VMess, Trojan and Shadowsocks inbounds.
- RAW/TCP, WebSocket, gRPC, HTTPUpgrade, XHTTP and mKCP transports; TLS and VLESS Reality.
- Validated advanced TLS/Reality, Sniffing, Sockopt and stream options, subscription ordering and host overrides.
- Subscription links, QR codes, Base64, raw links, Xray JSON, Clash Meta and Sing-box exports. Export compatibility depends on the selected protocol and transport.
- Individual and group access policies for inbounds and DNS tunnels.
- Administrator hierarchy, scoped permissions, plans and quotas.
- Local Xray management and a pull-based remote node agent.
- DNSTT and NoizDNS profile generation, DNS multiplexing and an optional authenticated local SOCKS gateway with per-user accounting.
- Node-specific Direct/WARP/Block routing with encrypted WireGuard credentials.
- Installation-specific Telegram bot: administrator user creation, subscription QR delivery and owner-only encrypted backups.
- SQLite or PostgreSQL, a quick server installer, Docker Compose, Nginx and systemd deployment.

This project is under active development. Server implementations for AmneziaWG, OpenVPN and other additional protocols are not part of the current release. Automated sales and payment processing are outside the project scope.

## Quick server setup

On a dedicated Debian/Ubuntu server (Python 3.11+), replace the domain and run:

```bash
curl -fsSLo /tmp/spectergate-install.sh https://raw.githubusercontent.com/SpecterLogic/SpecterGate/main/install.sh && sudo bash /tmp/spectergate-install.sh --domain panel.example.com --private-panel
```

Add `--database postgresql` for a local PostgreSQL database, or `--version TAG_OR_COMMIT` to select an existing version. SQLite is the default. The installer generates owner credentials, configures HTTPS and installs the `spectergate` management command. Your domain must point to the server, with TCP ports 80/443 reachable.

`--private-panel` puts management on a dedicated port and random URL path; allow that port in your provider firewall. Use `--panel-port PORT` to select the port. The full private URL is printed during installation. Public subscription paths remain available separately. HTTPS and administrator authentication are still required.

```bash
spectergate status
spectergate logs
sudo spectergate restart
```

See [installation, bot, backups and routing](docs/INSTALL.md) for paths, recovery and configuration. Each installation uses its owner's own Telegram bot token. Network filtering resistance depends on the configured transport, endpoint and client; connectivity must be tested on the intended networks.

## Local development

Requirements: Python 3.11+, Node.js 20+ and npm. Xray-core is required to validate and run generated Xray configurations.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
# Windows: .venv/Scripts/Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env
```

Set these values in `backend/.env` before starting:

```dotenv
SPECTERGATE_SECRET_KEY=<random-secret-at-least-32-characters>
SPECTERGATE_ADMIN_PASSWORD=<unique-password-at-least-12-characters>
SPECTERGATE_SESSION_COOKIE_SECURE=false
SPECTERGATE_PUBLIC_HOST=127.0.0.1
SPECTERGATE_SUBSCRIPTION_BASE_URL=http://127.0.0.1:8000
```

Use `SPECTERGATE_SESSION_COOKIE_SECURE=true` when serving through HTTPS. Sample passwords and placeholder secrets are rejected at startup. Set `SPECTERGATE_XRAY_BINARY` to the installed binary path.

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a separate terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The initial administrator username is `admin`; its password comes from the environment file. API documentation is disabled by default; set `SPECTERGATE_EXPOSE_API_DOCS=true` to expose `/api/docs`.

## Docker

```bash
cp .env.docker.example .env
# Replace all placeholder values and configure the public URL.
docker compose up -d --build
```

The web container binds to `127.0.0.1:8080`; put it behind a host HTTPS reverse proxy. For local HTTP-only testing, set `SPECTERGATE_SESSION_COOKIE_SECURE=false`. Publish every inbound TCP/UDP port that clients need. The optional PostgreSQL override is `docker-compose.postgres.yml`.

The backend manages local processes and listeners; run one API worker per instance. DNSTT server installation and DNS records are separate deployment steps described in the tunnel setup screen.

## Documentation

- [Server installation, bot and encrypted backups](docs/INSTALL.md)
- [Feature coverage and remaining compatibility work](docs/FEATURE_PARITY.md)
- [Access policies, subscriptions and tunnels](docs/ACCESS_AND_SUBSCRIPTIONS.md)
- [Architecture](ARCHITECTURE.md)
- [Remote node agent](agent/README.md)
- [Deployment files](deploy)

The subscription page is `/s/<token>`; the client subscription endpoint is `/sub/<token>`. Individual and group tokens can be revoked independently. Resource restrictions also apply to generated server configurations.

## Verification

```bash
cd backend
pytest

cd ../frontend
npm run build
```

Native configuration checks can be enabled with `XRAY_TEST_BINARY` pointing to an installed Xray executable. They validate server and exported client configurations, including VLESS Reality and XHTTP.

## Operational notes

- Back up the database and server key material before upgrades.
- Keep runtime databases, private keys and environment files outside version control.
- Local Xray reconciliation runs every 30 seconds while the managed core is running. Remote nodes use their configured polling interval.
- The local DNS SOCKS gateway checks active connections and commits traffic every second. External tunnel targets require their own authorization and accounting.
- Device-limit values are stored in plans; strict device/HWID enforcement is not implemented.
- Additional tables are created at startup. General versioned database migrations are not yet implemented.

## License

[MIT](LICENSE).
- [راهنمای فارسی از نصب تا ساخت کانفیگ](docs/GUIDE_FA.md)
