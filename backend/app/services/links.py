"""Build share links and Clash subscription payloads from inbound definitions."""

from __future__ import annotations

import base64
import json
from urllib.parse import quote, urlencode

from app.models import Inbound, Node, VPNUser
from app.services.settings import get_setting
from app.services.permissions import inbound_allowed
from app.services.inbound_options import client_port, client_flow, options, subscription_inbounds, client_sni, client_short_id


def _host_for(inbound: Inbound, node: Node | None, public_host: str) -> str:
    if options(inbound).share_host:
        return options(inbound).share_host
    if node and not node.is_local and node.address:
        return node.address
    return public_host or (node.address if node else "127.0.0.1")


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _query(**kwargs: str | None) -> str:
    pairs = [(key, value) for key, value in kwargs.items() if value]
    return urlencode(pairs, quote_via=quote)


def build_link(inbound: Inbound, node: Node | None, user: VPNUser, public_host: str) -> str | None:
    advanced = options(inbound)
    if inbound.network == 'kcp' or advanced.tcp_http_obfuscation:
        return None  # Use Xray JSON for transports that cannot be represented faithfully here.
    host = _host_for(inbound, node, public_host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    sni = advanced.reality.serverNames[0] if inbound.security == "reality" and advanced.reality.serverNames else inbound.sni
    short_id = advanced.reality.shortIds[0] if advanced.reality.shortIds else inbound.reality_short_id
    port = client_port(inbound)
    remark = quote(f"{inbound.remark} | {user.username}")
    network = inbound.network if inbound.network != "tcp" else None

    if inbound.protocol == "vless":
        params = _query(
            encryption="none",
            security=inbound.security if inbound.security != "none" else None,
            sni=sni if inbound.security in {"tls", "reality"} else None,
            fp=inbound.fingerprint if inbound.security in {"tls", "reality"} else None,
            pbk=inbound.reality_public_key if inbound.security == "reality" else None,
            sid=short_id if inbound.security == "reality" else None,
            spx=advanced.reality.spiderX if inbound.security == "reality" else None,
            type=network,
            host=inbound.host if inbound.network in {"ws", "httpupgrade", "xhttp"} else None,
            path=inbound.path if inbound.network in {"ws", "httpupgrade", "xhttp"} else None,
            mode=advanced.xhttp.mode if inbound.network == "xhttp" else None,
            serviceName=inbound.service_name if inbound.network == "grpc" else None,
            alpn=inbound.alpn if inbound.security == "tls" else None,
            flow=client_flow(inbound) if inbound.network == "tcp" and inbound.security != "none" else None,
        )
        return f"vless://{user.uuid}@{host}:{port}?{params}#{remark}"

    if inbound.protocol == "vmess":
        payload = {
            "v": "2",
            "ps": f"{inbound.remark} | {user.username}",
            "add": host.strip("[]"),
            "port": str(port),
            "id": user.uuid,
            "aid": "0",
            "scy": "auto",
            "net": inbound.network,
            "type": "none",
            "host": inbound.host or "",
            "path": inbound.path or "",
            "tls": "tls" if inbound.security == "tls" else "",
            "sni": inbound.sni or "",
            "alpn": inbound.alpn or "",
            "fp": inbound.fingerprint or "",
        }
        if inbound.network == "grpc":
            payload["path"] = inbound.service_name or ""
        return "vmess://" + _b64(json.dumps(payload, ensure_ascii=False))

    if inbound.protocol == "trojan":
        params = _query(
            security=inbound.security if inbound.security != "none" else None,
            sni=sni if inbound.security in {"tls", "reality"} else None,
            type=network,
            host=inbound.host if inbound.network in {"ws", "httpupgrade", "xhttp"} else None,
            path=inbound.path if inbound.network in {"ws", "httpupgrade", "xhttp"} else None,
            serviceName=inbound.service_name if inbound.network == "grpc" else None,
            alpn=inbound.alpn if inbound.security == "tls" else None,
            fp=inbound.fingerprint if inbound.security == "tls" else None,
        )
        return f"trojan://{quote(user.password)}@{host}:{port}?{params}#{remark}"

    if inbound.protocol == "shadowsocks":
        if inbound.network != 'tcp' or inbound.security != 'none':
            return None
        userinfo = _b64(f"chacha20-ietf-poly1305:{user.password}")
        return f"ss://{userinfo}@{host}:{port}#{remark}"

    return None


def subscription_links(
    user: VPNUser, inbounds: list[Inbound], nodes: dict[int, Node], public_host: str
) -> list[dict]:
    links: list[dict] = []
    for inbound in subscription_inbounds(inbounds):
        if user.status != "active" or not inbound_allowed(user, inbound.id):
            continue
        node = nodes.get(inbound.node_id) if inbound.node_id else None
        uri = build_link(inbound, node, user, public_host)
        if not uri:
            continue
        links.append(
            {
                "remark": f"{inbound.remark} | {user.username}",
                "protocol": inbound.protocol,
                "uri": uri,
            }
        )
    return links


def links_to_base64(links: list[dict]) -> str:
    payload = "\n".join(link["uri"] for link in links)
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def build_group_clash_config(
    members: list[VPNUser], inbounds: list[Inbound], nodes: dict[int, Node], public_host: str
) -> str:
    """Merge per-member Clash proxies into one profile for a multi-user subscription."""
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return ""

    proxies: list[dict] = []
    for member in members:
        if member.status != "active":
            continue
        raw = build_clash_config(member, [], inbounds, nodes, public_host)
        try:
            config = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            continue
        proxies.extend(config.get("proxies") or [])
    names = [proxy["name"] for proxy in proxies]
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "SPECTERGATE", "type": "select", "proxies": names or ["DIRECT"]},
            {
                "name": "AUTO",
                "type": "url-test",
                "proxies": names or ["DIRECT"],
                "url": "https://www.gstatic.com/generate_204",
                "interval": 300,
            },
        ],
        "rules": ["MATCH,SPECTERGATE"],
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def build_clash_config(user: VPNUser, links: list[dict], inbounds: list[Inbound], nodes: dict[int, Node], public_host: str) -> str:
    """Create a small, valid Clash Meta configuration. No external YAML dependency."""
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a declared dependency
        return ""

    proxies: list[dict] = []
    for inbound in subscription_inbounds(inbounds):
        if inbound.protocol == "shadowsocks" and (inbound.network != "tcp" or inbound.security != "none"):
            continue
        if user.status != "active" or not inbound_allowed(user, inbound.id):
            continue
        if inbound.network in {"xhttp", "kcp"} or options(inbound).tcp_http_obfuscation:
            continue  # XHTTP profiles are delivered through Xray JSON or share links.
        host = _host_for(inbound, nodes.get(inbound.node_id) if inbound.node_id else None, public_host)
        name = f"{inbound.remark} | {user.username}"
        if inbound.protocol == "vless":
            entry: dict = {
                "name": name,
                "type": "vless",
                "server": host,
                "port": client_port(inbound),
                "uuid": user.uuid,
                "udp": True,
                "network": inbound.network,
                "tls": inbound.security in {"tls", "reality"},
                "servername": client_sni(inbound),
                "client-fingerprint": inbound.fingerprint or "chrome",
            }
            if inbound.security == "reality":
                entry["reality-opts"] = {
                    "public-key": inbound.reality_public_key,
                    "short-id": client_short_id(inbound) or "",
                }
            if client_flow(inbound) and inbound.network == "tcp":
                entry["flow"] = client_flow(inbound)
            if inbound.network == "ws":
                entry["ws-opts"] = {
                    "path": inbound.path or "/",
                    "headers": {"Host": inbound.host or client_sni(inbound) or host},
                }
            elif inbound.network == "grpc":
                entry["grpc-opts"] = {"grpc-service-name": inbound.service_name or ""}
            elif inbound.network == "httpupgrade":
                entry["http-opts"] = {"path": [inbound.path or "/"]}
            proxies.append({key: value for key, value in entry.items() if value is not None})
        elif inbound.protocol == "vmess":
            entry = {
                "name": name,
                "type": "vmess",
                "server": host,
                "port": client_port(inbound),
                "uuid": user.uuid,
                "alterId": 0,
                "cipher": "auto",
                "udp": True,
                "network": inbound.network,
                "tls": inbound.security == "tls",
                "servername": client_sni(inbound),
            }
            if inbound.network == "ws":
                entry["ws-opts"] = {"path": inbound.path or "/", "headers": {"Host": inbound.host or host}}
            elif inbound.network == "grpc":
                entry["grpc-opts"] = {"grpc-service-name": inbound.service_name or ""}
            proxies.append({key: value for key, value in entry.items() if value is not None})
        elif inbound.protocol == "trojan":
            entry = {
                "name": name,
                "type": "trojan",
                "server": host,
                "port": client_port(inbound),
                "password": user.password,
                "udp": True,
                "sni": client_sni(inbound),
                "network": inbound.network,
            }
            proxies.append({key: value for key, value in entry.items() if value is not None})
        elif inbound.protocol == "shadowsocks":
            proxies.append(
                {
                    "name": name,
                    "type": "ss",
                    "server": host,
                    "port": client_port(inbound),
                    "cipher": "chacha20-ietf-poly1305",
                    "password": user.password,
                    "udp": True,
                }
            )

    names = [proxy["name"] for proxy in proxies]
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "SPECTERGATE", "type": "select", "proxies": names or ["DIRECT"]},
            {"name": "AUTO", "type": "url-test", "proxies": names or ["DIRECT"], "url": "https://www.gstatic.com/generate_204", "interval": 300},
        ],
        "rules": ["MATCH,SPECTERGATE"],
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
