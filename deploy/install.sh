#!/usr/bin/env bash
# SpecterGate bare-metal installer for Debian/Ubuntu.
# Usage: sudo CERTBOT_EMAIL=you@example.com bash deploy/install.sh panel.example.com
set -euo pipefail

DOMAIN="${1:-}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
APP_DIR="/opt/spectergate"
WEB_ROOT="/var/www/spectergate"
XRAY_VERSION="${XRAY_VERSION:-26.3.27}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$DOMAIN" ]]; then
  echo "Usage: sudo CERTBOT_EMAIL=you@example.com bash deploy/install.sh panel.example.com" >&2
  exit 1
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "This installer must run as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx \
  curl unzip rsync openssl ca-certificates

# Node.js 22 is required by the Vite build.
if ! command -v node >/dev/null 2>&1 || [[ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

# Xray-core (panel validates and supervises this binary).
if [[ ! -x /usr/local/bin/xray ]]; then
  case "$(uname -m)" in
    x86_64) XRAY_ASSET="Xray-linux-64.zip" ;;
    aarch64|arm64) XRAY_ASSET="Xray-linux-arm64-v8a.zip" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  mkdir -p /usr/local/share/xray
  curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${XRAY_ASSET}" -o /tmp/xray.zip
  unzip -q /tmp/xray.zip -d /usr/local/share/xray
  install -m 0755 /usr/local/share/xray/xray /usr/local/bin/xray
  rm -f /tmp/xray.zip
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
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-20)}"
  SECRET_KEY="$(openssl rand -hex 32)"
  cat > "$APP_DIR/backend/.env" <<EOF
SPECTERGATE_SECRET_KEY=$SECRET_KEY
SPECTERGATE_ADMIN_USERNAME=admin
SPECTERGATE_ADMIN_PASSWORD=$ADMIN_PASSWORD
SPECTERGATE_PUBLIC_HOST=$DOMAIN
SPECTERGATE_SUBSCRIPTION_BASE_URL=https://$DOMAIN
SPECTERGATE_CORS_ORIGINS=https://$DOMAIN
SPECTERGATE_DATABASE_URL=sqlite:///./data/spectergate.db
SPECTERGATE_XRAY_ENABLED=true
SPECTERGATE_XRAY_BINARY=/usr/local/bin/xray
SPECTERGATE_XRAY_CONFIG_PATH=./data/xray/config.json
SPECTERGATE_XRAY_LOG_PATH=./data/xray/xray.log
SPECTERGATE_XRAY_API_ADDRESS=127.0.0.1:10085
SPECTERGATE_DEMO_DATA=false
EOF
  echo "──────────────────────────────────────────────"
  echo "Admin username: admin"
  echo "Admin password: $ADMIN_PASSWORD"
  echo "Save this password; it is not shown again."
  echo "──────────────────────────────────────────────"
fi
chown spectergate:spectergate "$APP_DIR/backend/.env"
chmod 600 "$APP_DIR/backend/.env"

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

# Obtain a certificate with a temporary HTTP-only Nginx site, then install the
# full TLS config. This avoids Nginx failing on missing certificate files.
cat > /etc/nginx/sites-available/spectergate <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    root $WEB_ROOT;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { try_files \$uri /index.html; }
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
echo "Panel: https://$DOMAIN"
echo "API docs: https://$DOMAIN/api/docs"
echo "Node agent and DNS router are installed but not enabled; configure their env/config first."
