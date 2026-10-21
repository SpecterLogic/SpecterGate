import json
import socket

SOCKET_PATH = "/run/spectergate-ssl/control.sock"


def issue(domain, email=None):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(210)
            connection.connect(SOCKET_PATH)
            connection.sendall(json.dumps({"action": "issue", "domain": domain, "email": email}).encode() + b"\n")
            with connection.makefile("rb") as stream:
                result = json.loads(stream.readline(8192))
        if "error" in result:
            raise RuntimeError(result["error"])
        return result
    except (OSError, ValueError, AttributeError):
        raise RuntimeError("Certificate worker unavailable") from None
