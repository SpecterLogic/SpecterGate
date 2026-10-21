#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
apt-get update -qq
apt-get install -y fail2ban python3-systemd
SSH_PORT=$(sshd -T 2>/dev/null | awk '/^port / {print $2; exit}')
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || SSH_PORT=22
ACTION=nftables-multiport
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then ACTION=ufw; fi
cat > /etc/fail2ban/jail.d/spectergate-sshd.local <<EOF
[sshd]
enabled = true
backend = systemd
banaction = $ACTION
port = $SSH_PORT
maxretry = 5
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ::1
EOF
fail2ban-client -t
systemctl enable --now fail2ban
systemctl restart fail2ban
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if id spectergate >/dev/null 2>&1; then
  install -m 755 "$REPO_DIR/deploy/security_bridge.py" /usr/local/lib/spectergate-security-bridge.py
  install -m 644 "$REPO_DIR/deploy/spectergate-security.service" /etc/systemd/system/spectergate-security.service
  systemctl daemon-reload
  systemctl enable --now spectergate-security
  systemctl restart spectergate-security
fi
echo 'Fail2ban SSH protection enabled: 5 failures in 10 minutes, ban for 1 hour.'
