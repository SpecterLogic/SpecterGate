#!/usr/bin/env python3
"""Small domain-based DNS multiplexer for multiple DNSTT/NoizDNS tunnels.

Listens on UDP/53 and forwards each query to the tunnel instance responsible for
the longest matching domain suffix. Standard library only.

Config:
{
  "listen": "0.0.0.0:53",
  "routes": [
    {"domain": "t.example.com", "upstream": "127.0.0.1:5310"},
    {"domain": "n.example.com", "upstream": "127.0.0.1:5311"}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import selectors
import socket
import time
from pathlib import Path


def parse_qname(packet: bytes) -> str | None:
    if len(packet) < 13:
        return None
    labels: list[str] = []
    offset = 12
    while offset < len(packet):
        length = packet[offset]
        offset += 1
        if length == 0:
            return ".".join(labels).lower()
        if length & 0xC0:
            return None
        if offset + length > len(packet):
            return None
        labels.append(packet[offset : offset + length].decode("ascii", errors="ignore"))
        offset += length
    return None


def servfail(query: bytes) -> bytes:
    response = bytearray(query)
    if len(response) >= 4:
        response[2] |= 0x80  # QR
        response[3] = (response[3] & 0xF0) | 0x02  # SERVFAIL
    return bytes(response)


class Router:
    def __init__(self, config: dict) -> None:
        self.listen = config.get("listen", "0.0.0.0:53")
        self.routes = []
        for route in config.get("routes", []):
            domain = str(route["domain"]).strip(".").lower()
            host, port = str(route["upstream"]).rsplit(":", 1)
            self.routes.append((domain, (host, int(port))))
        self.routes.sort(key=lambda item: len(item[0]), reverse=True)
        self.selector = selectors.DefaultSelector()
        self.pending: dict[int, tuple[socket.socket, tuple, float, bytes]] = {}
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        host, port = self.listen.rsplit(":", 1)
        self.listener.bind((host, int(port)))
        self.listener.setblocking(False)
        self.selector.register(self.listener, selectors.EVENT_READ, None)

    def upstream_for(self, qname: str):
        for domain, upstream in self.routes:
            if qname == domain or qname.endswith("." + domain):
                return upstream
        return None

    def forward(self, query: bytes, client: tuple, upstream: tuple) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            sock.sendto(query, upstream)
        except OSError:
            sock.close()
            return
        self.selector.register(sock, selectors.EVENT_READ, "response")
        self.pending[sock.fileno()] = (sock, client, time.monotonic() + 4.0, query)

    def close_pending(self, fileno: int) -> None:
        item = self.pending.pop(fileno, None)
        if not item:
            return
        sock, client, _, query = item
        try:
            self.selector.unregister(sock)
        except (KeyError, ValueError):
            pass
        sock.close()
        try:
            self.listener.sendto(servfail(query), client)
        except OSError:
            pass

    def run(self) -> None:
        try:
            while True:
                for key, _mask in self.selector.select(timeout=0.25):
                    if key.fileobj is self.listener:
                        query, client = self.listener.recvfrom(4096)
                        qname = parse_qname(query)
                        upstream = self.upstream_for(qname) if qname else None
                        if upstream is None:
                            try:
                                self.listener.sendto(servfail(query), client)
                            except OSError:
                                pass
                            continue
                        self.forward(query, client, upstream)
                        continue
                    fileno = key.fd
                    item = self.pending.get(fileno)
                    if item is None:
                        continue
                    sock, client, _, _ = item
                    try:
                        response, _ = sock.recvfrom(65535)
                        self.listener.sendto(response, client)
                    except OSError:
                        pass
                    try:
                        self.selector.unregister(sock)
                    except (KeyError, ValueError):
                        pass
                    sock.close()
                    self.pending.pop(fileno, None)
                now = time.monotonic()
                for fileno, (_sock, _client, deadline, _query) in list(self.pending.items()):
                    if deadline < now:
                        self.close_pending(fileno)
        finally:
            self.listener.close()
            for sock, _client, _deadline, _query in self.pending.values():
                sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="SpecterGate DNS tunnel multiplexer")
    parser.add_argument("--config", default="/etc/spectergate/dns-router.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    Router(config).run()


if __name__ == "__main__":
    main()
