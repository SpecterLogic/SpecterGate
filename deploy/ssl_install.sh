#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
APP_DIR=/opt/spectergate
id spectergate >/dev/null
apt-get update -qq
apt-get install -y certbot python3-certbot-nginx
install -d -o root -g spectergate -m 750 /var/lib/spectergate-certificates
install -m 755 "$APP_DIR/deploy/ssl_bridge.py" /usr/local/lib/spectergate-ssl-bridge.py
install -m 755 "$APP_DIR/deploy/ssl_deploy.py" /usr/local/lib/spectergate-ssl-deploy.py
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/90-spectergate-nginx <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/90-spectergate-nginx
cat > /etc/systemd/system/spectergate-ssl.service <<'EOF'
[Unit]
Description=SpecterGate certificate worker
After=network-online.target nginx.service
[Service]
Group=spectergate
RuntimeDirectory=spectergate-ssl
RuntimeDirectoryMode=0750
ExecStart=/usr/bin/python3 /usr/local/lib/spectergate-ssl-bridge.py
Restart=on-failure
UMask=0077
NoNewPrivileges=true
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now certbot.timer spectergate-ssl.service
echo 'Certificate worker ready. Public DNS and TCP 80 must reach Nginx.'
