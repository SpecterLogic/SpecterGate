#!/usr/bin/env python3
"""Certbot deploy hook: export managed certificates with controlled permissions."""
import grp
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def deploy(domain):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]", domain) or ".." in domain:
        raise ValueError("Invalid certificate domain")
    source = Path("/etc/letsencrypt/live") / ("sg-" + domain)
    destination = Path("/var/lib/spectergate-certificates") / domain
    gid = grp.getgrnam("spectergate").gr_gid
    destination.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(destination, 0, gid)
    os.chmod(destination, 0o750)
    for name in ("fullchain.pem", "privkey.pem"):
        fd, temporary = tempfile.mkstemp(dir=destination)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write((source / name).read_bytes())
            os.chown(temporary, 0, gid)
            os.chmod(temporary, 0o640)
            os.replace(temporary, destination / name)
        finally:
            Path(temporary).unlink(missing_ok=True)
    subprocess.run(["/usr/sbin/nginx", "-t"], check=True, capture_output=True, timeout=10)
    subprocess.run(["/usr/bin/systemctl", "reload", "nginx"], check=True, timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        deploy(sys.argv[1])
    else:
        lineage = Path(os.environ.get("RENEWED_LINEAGE", ""))
        if lineage.parent != Path("/etc/letsencrypt/live") or not lineage.name.startswith("sg-"):
            raise SystemExit("Unexpected renewal lineage")
        deploy(lineage.name[3:])
