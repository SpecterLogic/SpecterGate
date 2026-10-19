"""DNSTT / NoizDNS profile generation.

The panel does not run the DNS tunnel daemon itself; it generates keys, server
commands, DNS routing config and client `slipnet://` URIs. The URI layout is
compatible with SlipNet/SlipGate v22 (60 pipe-delimited fields, base64 encoded).
"""

from __future__ import annotations

import base64
import re
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.models import DnsTunnel, VPNUser
from app.services.resource_access import tunnel_allowed


TOTAL_FIELDS = 60
FIELD_VERSION = 0
FIELD_TYPE = 1
FIELD_NAME = 2
FIELD_DOMAIN = 3
FIELD_RESOLVERS = 4
FIELD_AUTH_MODE = 5
FIELD_KEEPALIVE = 6
FIELD_CONGESTION = 7
FIELD_TCP_LISTEN_PORT = 8
FIELD_TCP_LISTEN_HOST = 9
FIELD_GSO = 10
FIELD_PUBLIC_KEY = 11
FIELD_SOCKS_USER = 12
FIELD_SOCKS_PASS = 13
FIELD_SSH_ENABLED = 14
FIELD_SSH_USER = 15
FIELD_SSH_PASS = 16
FIELD_SSH_PORT = 17
FIELD_FWD_DNS_SSH = 18
FIELD_SSH_HOST = 19
FIELD_USE_SERVER_DNS = 20
FIELD_DOH_URL = 21
FIELD_DNS_TRANSPORT = 22
FIELD_SSH_AUTH_TYPE = 23
FIELD_SSH_PRIVATE_KEY = 24
FIELD_SSH_KEY_PASSPHRASE = 25
FIELD_TOR_BRIDGES = 26
FIELD_DNSTT_AUTH = 27
FIELD_NAIVE_PORT = 28
FIELD_NAIVE_USER = 29
FIELD_NAIVE_PASS = 30
FIELD_IS_LOCKED = 31
FIELD_LOCK_HASH = 32
FIELD_EXPIRATION = 33
FIELD_ALLOW_SHARING = 34
FIELD_BOUND_DEVICE = 35
FIELD_RESOLVERS_HIDDEN = 36
FIELD_HIDDEN_RESOLVERS = 37
FIELD_NOIZDNS_STEALTH = 38
FIELD_DNS_PAYLOAD = 39
FIELD_SOCKS_PORT = 40

DEFAULT_RESOLVER = "8.8.8.8:53:0"


def generate_keypair() -> dict[str, str]:
    private = X25519PrivateKey.generate()
    private_hex = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return {"private_key": private_hex, "public_key": public_hex}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower())
    return value.strip("-") or "tunnel"


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode() if value else ""


def slipnet_uri(tunnel: DnsTunnel, user: VPNUser, mode: str = "dnstt") -> str:
    """Build a SlipNet v22 URI. NoizDNS is exposed as the legacy `sayedns` type."""
    if mode not in {"dnstt", "noizdns"}:
        raise ValueError("mode must be dnstt or noizdns")
    fields = [""] * TOTAL_FIELDS
    fields[FIELD_VERSION] = "22"
    fields[FIELD_TYPE] = "sayedns" if mode == "noizdns" else "dnstt"
    fields[FIELD_NAME] = f"{mode}-{tunnel.name}"[:80]
    fields[FIELD_DOMAIN] = tunnel.domain.strip(".")
    fields[FIELD_RESOLVERS] = tunnel.resolver or DEFAULT_RESOLVER
    fields[FIELD_AUTH_MODE] = "0"
    fields[FIELD_KEEPALIVE] = "5000"
    fields[FIELD_CONGESTION] = "bbr"
    fields[FIELD_TCP_LISTEN_PORT] = "1080"
    fields[FIELD_TCP_LISTEN_HOST] = "127.0.0.1"
    fields[FIELD_GSO] = "0"
    fields[FIELD_PUBLIC_KEY] = tunnel.public_key
    fields[FIELD_SOCKS_USER] = user.username
    fields[FIELD_SOCKS_PASS] = user.password
    fields[FIELD_SSH_ENABLED] = "0"
    fields[FIELD_SSH_USER] = ""
    fields[FIELD_SSH_PASS] = ""
    fields[FIELD_SSH_PORT] = "22"
    fields[FIELD_FWD_DNS_SSH] = "0"
    fields[FIELD_SSH_HOST] = ""
    fields[FIELD_USE_SERVER_DNS] = "0"
    fields[FIELD_DOH_URL] = ""
    fields[FIELD_DNS_TRANSPORT] = "udp"
    fields[FIELD_SSH_AUTH_TYPE] = "password"
    fields[FIELD_SSH_PRIVATE_KEY] = _b64("")
    fields[FIELD_SSH_KEY_PASSPHRASE] = _b64("")
    fields[FIELD_TOR_BRIDGES] = _b64("")
    fields[FIELD_DNSTT_AUTH] = "0"
    fields[FIELD_NAIVE_PORT] = "443"
    fields[FIELD_NAIVE_USER] = ""
    fields[FIELD_NAIVE_PASS] = _b64("")
    fields[FIELD_IS_LOCKED] = "0"
    fields[FIELD_LOCK_HASH] = ""
    fields[FIELD_EXPIRATION] = "0"
    fields[FIELD_ALLOW_SHARING] = "0"
    fields[FIELD_BOUND_DEVICE] = ""
    fields[FIELD_RESOLVERS_HIDDEN] = "0"
    fields[FIELD_HIDDEN_RESOLVERS] = ""
    fields[FIELD_NOIZDNS_STEALTH] = "1" if mode == "noizdns" else "0"
    fields[FIELD_DNS_PAYLOAD] = "0"
    fields[FIELD_SOCKS_PORT] = "1080"
    payload = "|".join(fields)
    return "slipnet://" + base64.b64encode(payload.encode()).decode()


def dns_links_for_user(user: VPNUser, tunnels: list[DnsTunnel]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for tunnel in tunnels:
        if not tunnel.is_active or user.status != "active" or not tunnel_allowed(user, tunnel.id):
            continue
        links.append(
            {
                "id": tunnel.id,
                "remark": f"DNSTT · {tunnel.domain}",
                "protocol": "dnstt",
                "domain": tunnel.domain,
                "uri": slipnet_uri(tunnel, user, "dnstt"),
            }
        )
        if tunnel.noizdns_enabled:
            links.append(
                {
                    "id": tunnel.id,
                    "remark": f"NoizDNS · {tunnel.domain}",
                    "protocol": "noizdns",
                    "domain": tunnel.domain,
                    "uri": slipnet_uri(tunnel, user, "noizdns"),
                }
            )
    return links


def dns_records(tunnel: DnsTunnel, server_ip: str = "<SERVER_IP>") -> list[str]:
    domain = tunnel.domain.strip(".")
    parts = domain.split(".")
    parent = ".".join(parts[1:]) if len(parts) > 2 else domain
    ns_host = f"ns.{parent}"
    return [
        f"A     {ns_host}    {server_ip}",
        f"NS    {domain}    {ns_host}",
    ]


def server_setup(tunnel: DnsTunnel, server_ip: str = "<SERVER_IP>") -> dict[str, Any]:
    slug = slugify(tunnel.name)
    key_path = f"/etc/spectergate/dnstt/{slug}.key"
    target = f"{tunnel.target_host}:{tunnel.target_port}"
    command = (
        f"sudo install -d -m 700 /etc/spectergate/dnstt\n"
        f"printf '%s\\n' '{tunnel.private_key}' | sudo tee {key_path} >/dev/null\n"
        f"sudo chmod 600 {key_path}\n"
        f"sudo /usr/local/bin/dnstt-server -udp 127.0.0.1:{tunnel.upstream_port} "
        f"-privkey-file {key_path} -mtu {tunnel.mtu} {tunnel.domain} {target}"
    )
    systemd = f"""[Unit]
Description=SpecterGate DNSTT tunnel {tunnel.name}
After=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/dnstt-server -udp 127.0.0.1:{tunnel.upstream_port} -privkey-file {key_path} -mtu {tunnel.mtu} {tunnel.domain} {target}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"""
    template_user = VPNUser(username="<socks-user>", password="<socks-pass>")
    template_user.id = 0
    dnstt_template = slipnet_uri(tunnel, template_user, "dnstt")
    noiz_template = slipnet_uri(tunnel, template_user, "noizdns") if tunnel.noizdns_enabled else None
    return {
        "id": tunnel.id,
        "name": tunnel.name,
        "domain": tunnel.domain,
        "key_path": key_path,
        "command": command,
        "systemd_unit": systemd,
        "dns_records": dns_records(tunnel, server_ip),
        "multiplexer_entry": {
            "domain": tunnel.domain,
            "upstream": f"127.0.0.1:{tunnel.upstream_port}",
        },
        "client_uri_template_dnstt": dnstt_template,
        "client_uri_template_noizdns": noiz_template,
        "notes": [
            "رکوردهای A و NS را در DNS دامنه ثبت کنید و منتظر انتشار TTL بمانید.",
            "dnstt-server باید به یک SOCKS5 محلی با احراز هویت کاربران پنل وصل شود.",
            "پورت 53 UDP باید در فایروال باز باشد؛ پورت‌های محلی 5310+ نباید عمومی شوند.",
        ],
    }


def multiplexer_config(tunnels: list[DnsTunnel], listen: str = "0.0.0.0:53") -> dict[str, Any]:
    routes = [
        {"domain": tunnel.domain.strip("."), "upstream": f"127.0.0.1:{tunnel.upstream_port}"}
        for tunnel in tunnels
        if tunnel.is_active
    ]
    config = {"listen": listen, "routes": routes}
    return {
        "listen": listen,
        "routes": routes,
        "config": config,
        "command": "sudo python3 /opt/spectergate-agent/dns_router.py --config /etc/spectergate/dns-router.json",
    }
