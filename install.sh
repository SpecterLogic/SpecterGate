#!/usr/bin/env bash
# Download a selected SpecterGate release and run its server installer.
set -euo pipefail
VERSION=main
ARGS=()
while (($#)); do
  case "$1" in
    --version) VERSION="${2:?Missing version}"; shift 2 ;;
    --help|-h) echo 'Usage: sudo bash install.sh [--version TAG_OR_COMMIT] --domain panel.example.com [--database sqlite|postgresql]'; exit 0 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
[[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$ ]] || { echo 'Invalid version.' >&2; exit 1; }
[[ $(id -u) == 0 ]] || { echo 'Run as root (sudo bash install.sh ...).' >&2; exit 1; }
command -v apt-get >/dev/null || { echo 'Debian/Ubuntu is required.' >&2; exit 1; }
apt-get update
apt-get install -y curl ca-certificates tar
WORK=$(mktemp -d /tmp/spectergate-install.XXXXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
curl --proto '=https' --tlsv1.2 -fSL --retry 3 "https://github.com/SpecterLogic/SpecterGate/archive/${VERSION}.tar.gz" -o "$WORK/source.tar.gz"
mkdir "$WORK/source"
tar -xzf "$WORK/source.tar.gz" -C "$WORK/source" --strip-components=1 --no-same-owner
bash "$WORK/source/deploy/install.sh" "${ARGS[@]}"
