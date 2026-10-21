#!/usr/bin/env python3
"""Root-only Certbot worker. Only domain/email cross the Unix socket."""
import grp
import json
import logging
import os
from pathlib import Path
import pwd
import re
import socket
import socketserver
import struct
import subprocess

SOCKET = "/run/spectergate-ssl/control.sock"


def validate_domain(value):
    if not isinstance(value, str) or len(value) > 253 or "." not in value:
        raise ValueError("Invalid public domain")
    if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split(".")):
        raise ValueError("Invalid public domain")
    return value


def dispatch(body):
    if not isinstance(body, dict) or body.get("action") != "issue":
        raise ValueError("Unsupported certificate action")
    domain = validate_domain(body.get("domain"))
    email = body.get("email")
    if email is not None and (not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
        raise ValueError("Invalid email")
    command = ["/usr/bin/certbot", "certonly", "--nginx", "--non-interactive", "--agree-tos", "--keep-until-expiring", "--cert-name", "sg-" + domain, "-d", domain,
               "--deploy-hook", "/usr/local/lib/spectergate-ssl-deploy.py"]
    command += ["--email", email] if email else ["--register-unsafely-without-email"]
    result = subprocess.run(command, capture_output=True, timeout=180)
    if result.returncode:
        logging.error("Certbot issuance failed for %s: %s", domain, result.stderr.decode(errors="replace")[-4000:])
        raise ValueError("Certificate issuance failed; inspect the SSL worker journal and public DNS/port 80.")
    # Also export when --keep-until-expiring did not run the renewal hook.
    subprocess.run(["/usr/local/lib/spectergate-ssl-deploy.py", domain], check=True, timeout=20)
    directory = Path("/var/lib/spectergate-certificates") / domain
    return {"cert_path": str(directory / "fullchain.pem"), "key_path": str(directory / "privkey.pem")}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            _, uid, _ = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid not in {0, pwd.getpwnam("spectergate").pw_uid}:
                return
            raw = self.rfile.readline(4097)
            if len(raw) > 4096 or not raw.endswith(b"\n"):
                raise ValueError("Invalid request")
            result = dispatch(json.loads(raw))
        except Exception:
            result = {"error": "Certificate operation failed; check the SSL worker journal."}
        self.wfile.write(json.dumps(result).encode() + b"\n")


if __name__ == "__main__":
    os.umask(0o077)
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam("spectergate").gr_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever()
