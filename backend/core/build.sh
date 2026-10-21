#!/usr/bin/env bash
set -euo pipefail
# Audited upstream tag v26.3.27. Never build a moving branch.
revision=d2758a023cd7f4174a5a5fa4ff66e487d4342ba0
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
output=${1:?Usage: build.sh /absolute/output/xray}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
git -C "$work" init -q
git -C "$work" remote add origin https://github.com/XTLS/Xray-core.git
git -C "$work" fetch --depth 1 origin "$revision"
git -C "$work" checkout -q FETCH_HEAD
test "$(git -C "$work" rev-parse HEAD)" = "$revision"
python3 "$here/patch.py" "$work"
cd "$work"
export GOTOOLCHAIN=auto GOMAXPROCS=${GOMAXPROCS:-2}
if ! command -v go >/dev/null || ! go version | python3 -c 'import re,sys; v=re.search(r"go(\d+)\.(\d+)",sys.stdin.read()); sys.exit(0 if v and tuple(map(int,v.groups())) >= (1,26) else 1)'; then
  python3 "$here/toolchain.py" "$work/toolchain"
  export PATH="$work/toolchain/go/bin:$PATH"
fi
env -u GOOS -u GOARCH go test -race ./common/spectergate
go build -p 2 -trimpath -ldflags='-s -w' -o "$output" ./main
