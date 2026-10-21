#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
AWG_PORT=51821
[[ ! -f /etc/amnezia/amneziawg/spectergate-port ]] || AWG_PORT=$(cat /etc/amnezia/amneziawg/spectergate-port)
if (($#)); then
  [[ $# -eq 2 && $1 == --port ]] || { echo 'Usage: sudo bash amneziawg_install.sh [--port UDP_PORT]' >&2; exit 1; }
  AWG_PORT=$2
fi
[[ "$AWG_PORT" =~ ^[0-9]{1,5}$ ]] && ((10#$AWG_PORT >= 1 && 10#$AWG_PORT <= 65535)) || { echo 'Invalid AmneziaWG UDP port.' >&2; exit 1; }
AWG_PORT=$((10#$AWG_PORT))
APP_DIR=/opt/spectergate
[[ -d "$APP_DIR/backend" ]] || { echo "Install SpecterGate first." >&2; exit 1; }
apt-get update -qq
apt-get install -y build-essential git golang-go iptables ca-certificates
GO_VERSION=$(go env GOVERSION)
[[ "$GO_VERSION" =~ ^go1\.([0-9]+) ]] && (( BASH_REMATCH[1] >= 21 )) || { echo "Go 1.21+ is required to bootstrap the pinned Go toolchain." >&2; exit 1; }
BUILD_DIR=$(mktemp -d /tmp/spectergate-awg-build.XXXXXX)
trap 'rm -rf -- "$BUILD_DIR"' EXIT
git clone --quiet https://github.com/amnezia-vpn/amneziawg-go.git "$BUILD_DIR/go"
git -C "$BUILD_DIR/go" checkout --quiet b5928efb6ca19f0153958460c3d141f04abc5c2e
(cd "$BUILD_DIR/go" && GOTOOLCHAIN=auto GOMAXPROCS=2 go build -p 2 -trimpath -o "$BUILD_DIR/amneziawg-go" .)
install -m 755 "$BUILD_DIR/amneziawg-go" /usr/local/bin/amneziawg-go.new
mv -f /usr/local/bin/amneziawg-go.new /usr/local/bin/amneziawg-go
git clone --quiet https://github.com/amnezia-vpn/amneziawg-tools.git "$BUILD_DIR/tools"
git -C "$BUILD_DIR/tools" checkout --quiet ee0f0a9aa34ff0a0da4b3433b9512781cfe02843
make -C "$BUILD_DIR/tools/src" -j2
make -C "$BUILD_DIR/tools/src" install PREFIX=/usr/local WITH_WGQUICK=yes WITH_SYSTEMDUNITS=yes

install -d -m 700 /etc/amnezia/amneziawg
printf '%s\n' "$AWG_PORT" > /etc/amnezia/amneziawg/spectergate-port
chmod 600 /etc/amnezia/amneziawg/spectergate-port
if [[ ! -s /etc/amnezia/amneziawg/spectergate.key ]]; then
  umask 077
  /usr/local/bin/awg genkey > /etc/amnezia/amneziawg/spectergate.key
fi
WAN_IF=$(ip -4 route show default | awk 'NR==1 {print $5}')
[[ "$WAN_IF" =~ ^[a-zA-Z0-9_.:-]+$ ]] || { echo "No IPv4 default route." >&2; exit 1; }
if ! ip link show sg-awg0 >/dev/null 2>&1; then
  if ip -4 route show | grep -q '^10\.89\.'; then
    echo "10.89.0.0/24 overlaps an existing route; choose a different AmneziaWG pool before installing." >&2
    exit 1
  fi
fi
cat > /etc/sysctl.d/70-spectergate-amneziawg.conf <<'EOF'
net.ipv4.ip_forward=1
EOF
sysctl -p /etc/sysctl.d/70-spectergate-amneziawg.conf >/dev/null
umask 077
cat > /etc/amnezia/amneziawg/sg-awg0.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/amnezia/amneziawg/spectergate.key)
Address = 10.89.0.1/24
ListenPort = $AWG_PORT
MTU = 1280
Jc = 4
Jmin = 50
Jmax = 1000
S1 = 56
S2 = 56
H1 = 1234567890
H2 = 987654321
H3 = 1122334455
H4 = 554433221
PostUp = iptables -t nat -A POSTROUTING -s 10.89.0.0/24 -o $WAN_IF -j MASQUERADE; iptables -I FORWARD -i %i -o $WAN_IF -s 10.89.0.0/24 -j ACCEPT; iptables -I FORWARD -i $WAN_IF -o %i -d 10.89.0.0/24 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s 10.89.0.0/24 -o $WAN_IF -j MASQUERADE; iptables -D FORWARD -i %i -o $WAN_IF -s 10.89.0.0/24 -j ACCEPT; iptables -D FORWARD -i $WAN_IF -o %i -d 10.89.0.0/24 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
EOF
chmod 600 /etc/amnezia/amneziawg/{sg-awg0.conf,spectergate.key}
if [[ -f /etc/apparmor.d/wg ]] && command -v apparmor_parser >/dev/null; then
  install -d -m 755 /etc/apparmor.d/local
  touch /etc/apparmor.d/local/wg
  WG_RULE='  /run/spectergate-awg/sync.conf r,'
  grep -Fqx "$WG_RULE" /etc/apparmor.d/local/wg || printf '%s\n' "$WG_RULE" >> /etc/apparmor.d/local/wg
  apparmor_parser -r /etc/apparmor.d/wg
fi
install -m 755 "$APP_DIR/deploy/wireguard_agent.py" /usr/local/lib/spectergate-amneziawg-agent.py
cat > /etc/systemd/system/spectergate-amneziawg.service <<'EOF'
[Unit]
Description=SpecterGate native AmneziaWG peer synchronization
Requires=awg-quick@sg-awg0.service
After=awg-quick@sg-awg0.service
[Service]
Type=simple
Group=spectergate
RuntimeDirectory=spectergate-awg
RuntimeDirectoryMode=0750
ExecStart=/usr/bin/python3 /usr/local/lib/spectergate-amneziawg-agent.py --amnezia
ExecStopPost=-/usr/bin/python3 /usr/local/lib/spectergate-amneziawg-agent.py --amnezia --clear
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/run/spectergate-awg
CapabilityBoundingSet=CAP_NET_ADMIN CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER
[Install]
WantedBy=multi-user.target
EOF
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  ufw allow "$AWG_PORT/udp" comment 'SpecterGate AmneziaWG'
fi
systemctl daemon-reload
systemctl enable awg-quick@sg-awg0
systemctl restart awg-quick@sg-awg0
/usr/local/bin/awg set sg-awg0 listen-port "$AWG_PORT"
systemctl enable spectergate-amneziawg
systemctl restart spectergate-amneziawg
for attempt in {1..20}; do
  if python3 -c 'import json,time; from pathlib import Path; p=Path("/run/spectergate-awg/status.json"); d=json.loads(p.read_text()) if p.exists() else {}; raise SystemExit(0 if d.get("ready") and time.time()-d.get("updated_at",0)<15 else 1)' 2>/dev/null; then
    echo "AmneziaWG ready on UDP $AWG_PORT. Grant access to individual users in the panel."
    exit 0
  fi
  sleep 1
done
echo "AmneziaWG did not become ready; inspect journalctl -u spectergate-amneziawg." >&2
exit 1
