#!/usr/bin/env python3
"""Narrow Unix-socket bridge to Fail2ban. No shell or arbitrary commands."""
import grp
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import socket
import socketserver
import struct
import subprocess

SOCKET = "/run/spectergate-security/control.sock"
CLIENT = "/usr/bin/fail2ban-client"


def run(*arguments):
    result = subprocess.run([CLIENT, *arguments], capture_output=True, text=True, timeout=10)
    if result.returncode != 0: raise ValueError("Fail2ban command failed; check service and jail status.")
    return result.stdout.strip()


def dispatch(body):
    if not isinstance(body, dict): raise ValueError("Invalid request")
    action = body.get("action")
    jail = body.get("jail", "sshd")
    if jail != "sshd": raise ValueError("Only the managed SSH jail is supported.")
    if action == "status":
        text = run("status", jail)
        def number(label):
            match = re.search(re.escape(label) + r":\s*(\d+)", text)
            return int(match.group(1)) if match else 0
        return {"available": True, "jail": jail, "active": True, "currently_failed": number("Currently failed"), "total_failed": number("Total failed"), "currently_banned": number("Currently banned"), "total_banned": number("Total banned"), "banned_ips": run("get", jail, "banip").split(), "maxretry": int(run("get", jail, "maxretry")), "findtime": int(run("get", jail, "findtime")), "bantime": int(run("get", jail, "bantime"))}
    if action in {"ban", "unban"}:
        ip = ipaddress.ip_address(body.get("ip", ""))
        if action == "ban" and (not ip.is_global or ip.is_multicast): raise ValueError("Only a public host address may be banned.")
        run("set", jail, "banip" if action == "ban" else "unbanip", str(ip))
        return {"ok": True}
    if action == "configure":
        values = {}
        for key, low, high in (("maxretry", 3, 20), ("findtime", 60, 86400), ("bantime", 60, 604800)):
            value = body.get(key)
            if type(value) is not int or not low <= value <= high: raise ValueError("Invalid protection settings")
            values[key] = value
        path = Path("/etc/fail2ban/jail.d/zz-spectergate-panel.local")
        old = path.read_bytes() if path.exists() else None
        text = "[sshd]\n" + "".join(f"{key} = {value}\n" for key, value in values.items())
        path.write_text(text); path.chmod(0o600)
        try:
            run("-t")
            run("reload", jail)
        except Exception:
            if old is None: path.unlink(missing_ok=True)
            else: path.write_bytes(old)
            raise
        return {"ok": True}
    raise ValueError("Unsupported action")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            _, uid, _ = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            if uid not in {0, pwd.getpwnam("spectergate").pw_uid}: return
            raw = self.rfile.readline(4097)
            if len(raw) > 4096 or not raw.endswith(b"\n"): raise ValueError("Request too large")
            response = dispatch(json.loads(raw))
        except Exception:
            response = {"error": "Fail2ban operation unavailable or invalid; inspect the security service."}
        self.wfile.write(json.dumps(response).encode() + b"\n")


if __name__ == "__main__":
    os.umask(0o077)
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam("spectergate").gr_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever(poll_interval=0.5)
