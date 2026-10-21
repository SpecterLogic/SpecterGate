#!/usr/bin/env bash
# SpecterGate bare-metal installer for Debian/Ubuntu.
# Usage: sudo CERTBOT_EMAIL=you@example.com bash deploy/install.sh panel.example.com
set -euo pipefail

DOMAIN=""
DATABASE="sqlite"
PRIVATE_PANEL=false
PANEL_PORT=""
INSTALL_WIREGUARD=false
INSTALL_DNSTT=false
while (($#)); do
  case "$1" in
    --domain) DOMAIN="${2:?Missing domain}"; shift 2 ;;
    --database) DATABASE="${2:?Missing database}"; shift 2 ;;
    --private-panel) PRIVATE_PANEL=true; shift ;;
    --wireguard) INSTALL_WIREGUARD=true; shift ;;
    --dnstt) INSTALL_DNSTT=true; shift ;;
    --panel-port) PANEL_PORT="${2:?Missing port}"; PRIVATE_PANEL=true; shift 2 ;;
    --help|-h) echo 'Usage: sudo bash deploy/install.sh --domain panel.example.com [--database sqlite|postgresql] [--private-panel] [--panel-port PORT] [--wireguard] [--dnstt]'; exit 0 ;;
    --*) echo "Unknown option: $1" >&2; exit 1 ;;
    *) [[ -z "$DOMAIN" ]] || { echo 'Unexpected argument.' >&2; exit 1; }; DOMAIN="$1"; shift ;;
  esac
done
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
APP_DIR="/opt/spectergate"
WEB_ROOT="/var/www/spectergate"
XRAY_VERSION="${XRAY_VERSION:-26.3.27}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! "$DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,63}$ ]] || [[ "$DOMAIN" == *..* || ${#DOMAIN} -gt 253 ]]; then
  echo "Usage: sudo CERTBOT_EMAIL=you@example.com bash deploy/install.sh panel.example.com" >&2
  exit 1
fi
[[ "$DATABASE" == sqlite || "$DATABASE" == postgresql ]] || { echo 'Supported databases: sqlite, postgresql.' >&2; exit 1; }
if [[ -n "$PANEL_PORT" ]] && { [[ ! "$PANEL_PORT" =~ ^[0-9]{4,5}$ ]] || ((10#$PANEL_PORT < 1024 || 10#$PANEL_PORT > 65535)); }; then
  echo 'Panel port must be between 1024 and 65535.' >&2; exit 1
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "This installer must run as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
umask 022
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx \
  curl unzip rsync openssl ca-certificates

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo 'SpecterGate requires Python 3.11+. Use Ubuntu 24.04+ or Debian 12+, or configure a supported Python before installation.' >&2
  exit 1
fi

# Node.js 22 is required by the Vite build.
if ! command -v node >/dev/null 2>&1 || [[ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

# Xray-core (panel validates and supervises this binary).
if [[ ! -x /usr/local/bin/xray ]]; then
  case "$(uname -m)" in
    x86_64) XRAY_ASSET="Xray-linux-64.zip"; PINNED_HASH=23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae ;;
    aarch64|arm64) XRAY_ASSET="Xray-linux-arm64-v8a.zip"; PINNED_HASH=4d30283ae614e3057f730f67cd088a42be6fdf91f8639d82cb69e48cde80413c ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  if [[ "$XRAY_VERSION" != 26.3.27 && -z "${XRAY_SHA256:-}" ]]; then
    echo 'A custom Xray version requires XRAY_SHA256.' >&2; exit 1
  fi
  mkdir -p /usr/local/share/xray
  XRAY_WORK=$(mktemp -d /tmp/spectergate-xray.XXXXXXXX)
  trap 'rm -rf -- "$XRAY_WORK"' EXIT
  curl --proto '=https' -fsSL --retry 3 "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${XRAY_ASSET}" -o "$XRAY_WORK/xray.zip"
  printf '%s  %s\n' "${XRAY_SHA256:-$PINNED_HASH}" "$XRAY_WORK/xray.zip" | sha256sum -c -
  unzip -q "$XRAY_WORK/xray.zip" -d /usr/local/share/xray
  install -m 0755 /usr/local/share/xray/xray /usr/local/bin/xray
  rm -rf -- "$XRAY_WORK"
  trap - EXIT
fi

if ! id -u spectergate >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin spectergate
fi

mkdir -p "$APP_DIR" "$WEB_ROOT"
rsync -a \
  --exclude 'backend/data' \
  --exclude 'backend/.env' \
  --exclude 'backend/.venv' \
  --exclude 'backend/__pycache__' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude '.git' \
  "$REPO_DIR/" "$APP_DIR/"

# Downloaded source folders may be private temporary directories. rsync -a
# copies their root mode too; the service account must traverse the app root.
chmod 0755 "$APP_DIR"

# Build the frontend on the server.
cd "$APP_DIR/frontend"
npm ci
npm run build
rm -rf "$WEB_ROOT"/*
cp -r dist/. "$WEB_ROOT"/

# Python environment.
cd "$APP_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [[ ! -f "$APP_DIR/backend/.env" ]]; then
  umask 077
  DATABASE_URL='sqlite:///./data/spectergate.db'
  if [[ "$DATABASE" == postgresql ]]; then
    apt-get install -y postgresql postgresql-client
    systemctl enable --now postgresql
    DB_PASSWORD=$(openssl rand -hex 32)
    # Refuse to alter an existing database or role during a fresh install.
    if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='spectergate'" | grep -q 1; then
      echo 'PostgreSQL role spectergate already exists. Configure an existing installation explicitly.' >&2
      exit 1
    fi
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<SQL
CREATE ROLE spectergate LOGIN PASSWORD '$DB_PASSWORD';
CREATE DATABASE spectergate OWNER spectergate;
SQL
    DATABASE_URL="postgresql+psycopg://spectergate:$DB_PASSWORD@127.0.0.1:5432/spectergate"
  fi
  ADMIN_USERNAME="sg_$(openssl rand -hex 4)"
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-20)}"
  SECRET_KEY="$(openssl rand -hex 32)"
  cat > "$APP_DIR/backend/.env" <<EOF
SPECTERGATE_SECRET_KEY=$SECRET_KEY
SPECTERGATE_ADMIN_USERNAME=$ADMIN_USERNAME
SPECTERGATE_ADMIN_PASSWORD=$ADMIN_PASSWORD
SPECTERGATE_PUBLIC_HOST=$DOMAIN
SPECTERGATE_SUBSCRIPTION_BASE_URL=https://$DOMAIN
SPECTERGATE_CORS_ORIGINS=https://$DOMAIN
SPECTERGATE_DATABASE_URL=$DATABASE_URL
SPECTERGATE_SESSION_COOKIE_SECURE=true
SPECTERGATE_TRUSTED_HOSTS=$DOMAIN,127.0.0.1,localhost
SPECTERGATE_XRAY_ENABLED=true
SPECTERGATE_XRAY_BINARY=/usr/local/bin/xray
SPECTERGATE_XRAY_CONFIG_PATH=./data/xray/config.json
SPECTERGATE_XRAY_LOG_PATH=./data/xray/xray.log
SPECTERGATE_XRAY_API_ADDRESS=127.0.0.1:10085
SPECTERGATE_DEMO_DATA=false
EOF
  echo "──────────────────────────────────────────────"
  echo "Admin username: $ADMIN_USERNAME"
  echo "Admin password: $ADMIN_PASSWORD"
  echo "Save this password; it is not shown again."
  echo "──────────────────────────────────────────────"
fi
umask 022
chown spectergate:spectergate "$APP_DIR/backend/.env"
chmod 600 "$APP_DIR/backend/.env"
install -m 0755 "$APP_DIR/deploy/spectergate" /usr/local/bin/spectergate

mkdir -p "$APP_DIR/backend/data"
chown -R spectergate:spectergate "$APP_DIR/backend/data"
chown -R www-data:www-data "$WEB_ROOT"

install -m 0644 "$APP_DIR/deploy/spectergate.service" /etc/systemd/system/spectergate.service
mkdir -p /opt/spectergate-agent /etc/spectergate
install -m 0755 "$APP_DIR/agent/spectergate_agent.py" /opt/spectergate-agent/spectergate_agent.py
install -m 0755 "$APP_DIR/agent/dns_router.py" /opt/spectergate-agent/dns_router.py
install -m 0644 "$APP_DIR/deploy/spectergate-agent.service" /etc/systemd/system/spectergate-agent.service
install -m 0644 "$APP_DIR/deploy/spectergate-dns-router.service" /etc/systemd/system/spectergate-dns-router.service
systemctl daemon-reload
systemctl enable spectergate
systemctl restart spectergate

READY=false
for attempt in {1..30}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 1
done
if [[ "$READY" != true ]]; then
  echo 'SpecterGate did not become healthy. Inspect: journalctl -u spectergate' >&2
  exit 1
fi

# Obtain a certificate with a temporary HTTP-only Nginx site, then install the
# full TLS config. This avoids Nginx failing on missing certificate files.
cat > /etc/nginx/sites-available/spectergate <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    root $WEB_ROOT;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 503; }
}
NGINX
ln -sf /etc/nginx/sites-available/spectergate /etc/nginx/sites-enabled/spectergate
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  CERTBOT_ARGS=(certonly --webroot -w /var/www/html -d "$DOMAIN" --agree-tos --non-interactive)
  if [[ -n "$CERTBOT_EMAIL" ]]; then
    CERTBOT_ARGS+=(-m "$CERTBOT_EMAIL")
  else
    CERTBOT_ARGS+=(--register-unsafely-without-email)
  fi
  certbot "${CERTBOT_ARGS[@]}"
fi

sed "s/panel.example.com/$DOMAIN/g" "$APP_DIR/deploy/nginx/spectergate.conf" > /etc/nginx/sites-available/spectergate
nginx -t
systemctl reload nginx

echo "SpecterGate is installed."
bash "$APP_DIR/deploy/fail2ban_install.sh"
if [[ "$INSTALL_DNSTT" == true ]]; then
  bash "$APP_DIR/deploy/dnstt_install.sh"
fi
if [[ "$INSTALL_WIREGUARD" == true ]]; then
  bash "$APP_DIR/deploy/wireguard_install.sh"
fi
if [[ "$PRIVATE_PANEL" == true ]]; then
  ACCESS_ARGS=(--domain "$DOMAIN")
  [[ -z "$PANEL_PORT" ]] || ACCESS_ARGS+=(--port "$PANEL_PORT")
  python3 "$APP_DIR/deploy/panel_access.py" "${ACCESS_ARGS[@]}"
else
  echo "Panel: https://$DOMAIN"
fi
echo "Management: spectergate status | logs | restart | backup | decrypt-backup"
echo "Node agent and DNS router are installed but not enabled; configure their env/config first."
