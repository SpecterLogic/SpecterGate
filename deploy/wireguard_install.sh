#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
WG_PORT=51820
[[ ! -f /etc/wireguard/spectergate-port ]] || WG_PORT=$(cat /etc/wireguard/spectergate-port)
if (($#)); then
  [[ $# -eq 2 && $1 == --port ]] || { echo 'Usage: sudo bash wireguard_install.sh [--port UDP_PORT]' >&2; exit 1; }
  WG_PORT=$2
fi
[[ "$WG_PORT" =~ ^[0-9]{1,5}$ ]] && ((10#$WG_PORT >= 1 && 10#$WG_PORT <= 65535)) || { echo 'Invalid WireGuard UDP port.' >&2; exit 1; }
WG_PORT=$((10#$WG_PORT))
APP_DIR=/opt/spectergate
[[ -d "$APP_DIR/backend" ]] || { echo "Install SpecterGate first." >&2; exit 1; }
apt-get update -qq
apt-get install -y wireguard-tools iptables
install -d -m 700 /etc/wireguard
printf '%s\n' "$WG_PORT" > /etc/wireguard/spectergate-port
chmod 600 /etc/wireguard/spectergate-port
if [[ ! -s /etc/wireguard/spectergate.key ]]; then
  umask 077
  wg genkey > /etc/wireguard/spectergate.key
fi
WAN_IF=$(ip -4 route show default | awk 'NR==1 {print $5}')
[[ "$WAN_IF" =~ ^[a-zA-Z0-9_.:-]+$ ]] || { echo "No IPv4 default route." >&2; exit 1; }
if ! ip link show sg-wg0 >/dev/null 2>&1; then
  if ip -4 route show | grep -q '^10\.88\.'; then
    echo "10.88.0.0/16 overlaps an existing route; choose a different WireGuard pool before installing." >&2
    exit 1
  fi
fi
cat > /etc/sysctl.d/70-spectergate-wireguard.conf <<'EOF'
net.ipv4.ip_forward=1
EOF
sysctl -p /etc/sysctl.d/70-spectergate-wireguard.conf >/dev/null
umask 077
cat > /etc/wireguard/sg-wg0.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/spectergate.key)
Address = 10.88.0.1/16
ListenPort = $WG_PORT
MTU = 1280
PostUp = iptables -t nat -A POSTROUTING -s 10.88.0.0/16 -o $WAN_IF -j MASQUERADE; iptables -I FORWARD -i %i -o $WAN_IF -s 10.88.0.0/16 -j ACCEPT; iptables -I FORWARD -i $WAN_IF -o %i -d 10.88.0.0/16 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s 10.88.0.0/16 -o $WAN_IF -j MASQUERADE; iptables -D FORWARD -i %i -o $WAN_IF -s 10.88.0.0/16 -j ACCEPT; iptables -D FORWARD -i $WAN_IF -o %i -d 10.88.0.0/16 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
EOF
chmod 600 /etc/wireguard/{sg-wg0.conf,spectergate.key}
if [[ -f /etc/apparmor.d/wg ]] && command -v apparmor_parser >/dev/null; then
  install -d -m 755 /etc/apparmor.d/local
  touch /etc/apparmor.d/local/wg
  WG_RULE='  /run/spectergate-wg/sync.conf r,'
  grep -Fqx "$WG_RULE" /etc/apparmor.d/local/wg || printf '%s\n' "$WG_RULE" >> /etc/apparmor.d/local/wg
  apparmor_parser -r /etc/apparmor.d/wg
fi
install -m 755 "$APP_DIR/deploy/wireguard_agent.py" /usr/local/lib/spectergate-wireguard-agent.py
cat > /etc/systemd/system/spectergate-wireguard.service <<'EOF'
[Unit]
Description=SpecterGate native WireGuard peer synchronization
Requires=wg-quick@sg-wg0.service
After=wg-quick@sg-wg0.service
[Service]
Type=simple
Group=spectergate
RuntimeDirectory=spectergate-wg
RuntimeDirectoryMode=0750
ExecStart=/usr/bin/python3 /usr/local/lib/spectergate-wireguard-agent.py
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/run/spectergate-wg
CapabilityBoundingSet=CAP_NET_ADMIN CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER
[Install]
WantedBy=multi-user.target
EOF
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  ufw allow "$WG_PORT/udp" comment 'SpecterGate WireGuard'
fi
systemctl daemon-reload
systemctl enable --now wg-quick@sg-wg0
wg set sg-wg0 listen-port "$WG_PORT"
systemctl enable spectergate-wireguard
systemctl restart spectergate-wireguard
for attempt in {1..20}; do
  if python3 -c 'import json,time; from pathlib import Path; p=Path("/run/spectergate-wg/status.json"); d=json.loads(p.read_text()) if p.exists() else {}; raise SystemExit(0 if d.get("ready") and time.time()-d.get("updated_at",0)<15 else 1)' 2>/dev/null; then
    echo "WireGuard ready on UDP $WG_PORT. Grant access to individual users in the panel."
    exit 0
  fi
  sleep 1
done
echo "WireGuard did not become ready; inspect journalctl -u spectergate-wireguard." >&2
exit 1
