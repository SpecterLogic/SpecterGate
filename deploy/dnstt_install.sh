#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
APP_DIR=/opt/spectergate
[[ -f "$APP_DIR/backend/.env" ]] || { echo 'Install SpecterGate first.' >&2; exit 1; }
apt-get update -qq
apt-get install -y git golang-go
go version | awk '{print $3}' | python3 -c 'import sys; v=sys.stdin.read().strip().removeprefix("go").split("."); sys.exit(0 if tuple(map(int,v[:2])) >= (1,21) else 1)' || { echo 'Go 1.21+ is required; use Ubuntu 24.04+ or install a supported Go toolchain.' >&2; exit 1; }
WORK=$(mktemp -d /tmp/spectergate-dnstt.XXXXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
git clone --quiet https://www.bamsoftware.com/git/dnstt.git "$WORK/source"
git -C "$WORK/source" checkout --quiet 0c5c52a57d899c05428c116898941761a2ed83c2
(cd "$WORK/source" && go mod verify && go build -trimpath -o "$WORK/dnstt-server" ./dnstt-server)
install -m 755 "$WORK/dnstt-server" /usr/local/bin/dnstt-server
WAN_IF=$(ip -4 route show default | awk 'NR==1 {print $5}')
LISTEN_IP=${1:-$(ip -4 -o addr show dev "$WAN_IF" scope global | awk 'NR==1 {split($4,a,"/");print a[1]}')}
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$LISTEN_IP"
sed -i '/^SPECTERGATE_DNSTT_ENABLED=/d;/^SPECTERGATE_DNSTT_BINARY=/d;/^SPECTERGATE_DNS_LISTEN=/d' "$APP_DIR/backend/.env"
printf '\nSPECTERGATE_DNSTT_ENABLED=true\nSPECTERGATE_DNSTT_BINARY=/usr/local/bin/dnstt-server\nSPECTERGATE_DNS_LISTEN=%s:53\n' "$LISTEN_IP" >> "$APP_DIR/backend/.env"
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then ufw allow 53/udp comment 'SpecterGate DNSTT'; fi
systemctl restart spectergate
echo 'DNSTT binary and runtime enabled. Create a managed DNS tunnel in the panel and delegate its domain with NS records.'
