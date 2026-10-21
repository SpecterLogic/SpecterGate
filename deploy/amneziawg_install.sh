#!/usr/bin/env bash
# SpecterGate AmneziaWG installer with anti-censorship DPI obfuscation.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root (sudo bash amneziawg_install.sh)." >&2; exit 1; }

AWG_PORT=51821
APP_DIR=/opt/spectergate

if (($#)); then
  [[ $# -eq 2 && $1 == --port ]] || { echo 'Usage: sudo bash amneziawg_install.sh [--port UDP_PORT]' >&2; exit 1; }
  AWG_PORT=$2
fi

[[ "$AWG_PORT" =~ ^[0-9]{1,5}$ ]] && ((10#$AWG_PORT >= 1 && 10#$AWG_PORT <= 65535)) || { echo 'Invalid AmneziaWG UDP port.' >&2; exit 1; }

echo "=== Installing AmneziaWG Dependencies ==="
apt-get update -qq
apt-get install -y curl tar ca-certificates iptables

install -d -m 700 /etc/amnezia/amneziawg

# Download or verify amneziawg-go binary if not present
ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64) AWG_ARCH="amd64" ;;
  aarch64|arm64) AWG_ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

echo "Architecture detected: $AWG_ARCH"

# Enable IP forwarding
cat > /etc/sysctl.d/70-spectergate-amneziawg.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl -p /etc/sysctl.d/70-spectergate-amneziawg.conf >/dev/null

echo "AmneziaWG setup configured on UDP port $AWG_PORT."
echo "Use the SpecterGate panel under Inbounds/AmneziaWG to manage obfuscation parameters and download awg0.conf."
