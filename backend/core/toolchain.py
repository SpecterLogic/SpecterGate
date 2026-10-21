"""Install the fixed Go toolchain from Go's HTTPS release catalog."""
import hashlib
import json
import platform
from pathlib import Path
import sys
import tarfile
import urllib.request

version = "go1.26.8"
arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
if sys.platform != "linux" or not arch:
    raise SystemExit("Managed core build supports Linux amd64/arm64")
target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen("https://go.dev/dl/?mode=json&include=all", timeout=60) as stream:
    catalog = json.load(stream)
entry = next(file for release in catalog if release["version"] == version for file in release["files"]
             if file["os"] == "linux" and file["arch"] == arch and file["kind"] == "archive")
archive = target / "go.tar.gz"
with urllib.request.urlopen("https://go.dev/dl/" + entry["filename"], timeout=120) as source, archive.open("wb") as output:
    import shutil
    shutil.copyfileobj(source, output)
if hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
    raise SystemExit("Go archive checksum mismatch")
with tarfile.open(archive) as bundle:
    # The archive was verified against the official fixed-version catalog.
    for member in bundle.getmembers():
        if not (target / member.name).resolve().is_relative_to(target.resolve()):
            raise SystemExit("Invalid archive path")
    bundle.extractall(target)
archive.unlink()
