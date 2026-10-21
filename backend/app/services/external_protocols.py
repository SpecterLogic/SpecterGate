from __future__ import annotations

import secrets
import urllib.parse
from typing import Any


def generate_hysteria2_client_uri(
    server: str,
    port: int,
    password: str,
    sni: str = "www.bing.com",
    obfs_password: str | None = None,
    insecure: bool = False,
    remark: str = "SpecterGate-Hy2",
) -> str:
    """Generate standard hysteria2:// client connection link."""
    userinfo = urllib.parse.quote(password, safe="")
    query_params: dict[str, str] = {
        "sni": sni,
        "insecure": "1" if insecure else "0",
    }
    if obfs_password:
        query_params["obfs"] = "salamander"
        query_params["obfs-password"] = obfs_password

    query_str = urllib.parse.urlencode(query_params)
    enc_remark = urllib.parse.quote(remark)
    return f"hysteria2://{userinfo}@{server}:{port}/?{query_str}#{enc_remark}"


def generate_hysteria2_outbound(
    server: str,
    port: int,
    password: str,
    sni: str = "www.bing.com",
    obfs_password: str | None = None,
    insecure: bool = False,
    tag: str = "hysteria2-out",
) -> dict[str, Any]:
    """Generate Sing-box / Clash Meta hysteria2 outbound block."""
    outbound: dict[str, Any] = {
        "type": "hysteria2",
        "tag": tag,
        "server": server,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": sni,
            "insecure": insecure,
        },
    }
    if obfs_password:
        outbound["obfs"] = {
            "type": "salamander",
            "password": obfs_password,
        }
    return outbound


def generate_tuic_client_uri(
    server: str,
    port: int,
    uuid_str: str,
    password: str,
    sni: str = "www.bing.com",
    congestion_control: str = "bbr",
    remark: str = "SpecterGate-TUIC",
) -> str:
    """Generate standard tuic:// v5 client connection link."""
    userinfo = f"{urllib.parse.quote(uuid_str)}:{urllib.parse.quote(password)}"
    query = urllib.parse.urlencode({
        "congestion_control": congestion_control,
        "alpn": "h3",
        "sni": sni,
    })
    enc_remark = urllib.parse.quote(remark)
    return f"tuic://{userinfo}@{server}:{port}/?{query}#{enc_remark}"


def generate_tuic_outbound(
    server: str,
    port: int,
    uuid_str: str,
    password: str,
    sni: str = "www.bing.com",
    congestion_control: str = "bbr",
    tag: str = "tuic-out",
) -> dict[str, Any]:
    """Generate Sing-box tuic outbound block."""
    return {
        "type": "tuic",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid_str,
        "password": password,
        "congestion_control": congestion_control,
        "tls": {
            "enabled": True,
            "server_name": sni,
            "alpn": ["h3"],
        },
    }


def generate_shadowtls_outbound(
    server: str,
    port: int,
    password: str,
    sni: str = "cloud.cloudflare.com",
    version: int = 3,
    tag: str = "shadowtls-out",
) -> dict[str, Any]:
    """Generate ShadowTLS wrapper outbound configuration."""
    return {
        "type": "shadowtls",
        "tag": tag,
        "server": server,
        "server_port": port,
        "version": version,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": sni,
        },
    }


def generate_mtproto_fake_tls_secret(domain: str = "www.cloudflare.com") -> str:
    """
    Generate an MTProto Fake-TLS secret:
    'ee' prefix + 16 random hex bytes + ASCII hex encoding of the SNI domain.
    """
    random_hex = secrets.token_hex(16)
    domain_hex = domain.encode("utf-8").hex()
    return f"ee{random_hex}{domain_hex}"


def generate_mtproto_link(server: str, port: int, secret: str) -> str:
    """Generate standard tg:// and https://t.me/proxy Telegram MTProto link."""
    query = urllib.parse.urlencode({"server": server, "port": port, "secret": secret})
    return f"https://t.me/proxy?{query}"
