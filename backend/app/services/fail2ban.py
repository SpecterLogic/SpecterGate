import ipaddress
import json
import socket

SOCKET_PATH = "/run/spectergate-security/control.sock"


def command(action, **values):
    if not hasattr(socket, "AF_UNIX"): raise RuntimeError("Install the Linux security bridge first.")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(35)
            connection.connect(SOCKET_PATH)
            connection.sendall(json.dumps({"action": action, **values}).encode() + b"\n")
            with connection.makefile("rb") as response:
                raw = response.readline(256 * 1024)
            data = json.loads(raw)
            if "error" in data: raise RuntimeError("سرویس امنیت پاسخ موفق نداد؛ وضعیت Fail2ban را بررسی کنید.")
            return data
    except (OSError, ValueError):
        raise RuntimeError("سرویس مدیریت Fail2ban در دسترس نیست؛ نصب سرویس امنیت را بررسی کنید.") from None
