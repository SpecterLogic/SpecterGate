"""Install pinned auxiliary engine binaries; archives are never extracted to paths."""
import hashlib
import io
import os
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import urllib.request

RELEASES = {
    "singbox": ("SagerNet/sing-box", "1.14.3", "sing-box", {
        "amd64": "e2bdf179c15a3652955dc44867e33ca0965c9c9b91b34267dcc5a5d639a5feee",
        "arm64": "29dae24d76bea3bc62d07dd3e60cfc12003de7debbd6b768df9be9c68360174e",
    }),
    "mtg": ("9seconds/mtg", "2.2.8", "mtg", {
        "amd64": "7ef19d079d85f4e00d4f8334ec1f3f3c8718e3d0ed1f3109ea9a8673138a2102",
        "arm64": "562a94dd4cafcb8f179b76cfeafb76da12747c8e230bc76235bf8746cc189644",
    }),
}


def install(name, destination):
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if sys.platform != "linux" or not arch:
        raise SystemExit("Linux amd64/arm64 is required")
    repo, version, binary, hashes = RELEASES[name]
    url = f"https://github.com/{repo}/releases/download/v{version}/{binary}-{version}-linux-{arch}.tar.gz"
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read(100 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != hashes[arch]:
        raise SystemExit("Engine checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
        matches = [item for item in bundle if item.isfile() and Path(item.name).name == binary]
        if len(matches) != 1:
            raise SystemExit("Unexpected engine archive")
        content = bundle.extractfile(matches[0]).read()
    path = Path(destination)
    fd, candidate = tempfile.mkstemp(prefix=".sg-engine-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
        os.chmod(candidate, 0o755)
        os.replace(candidate, path)
    finally:
        Path(candidate).unlink(missing_ok=True)


if __name__ == "__main__":
    install(sys.argv[1], sys.argv[2])
