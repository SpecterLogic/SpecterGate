"""Client profiles for the protocols implemented by this panel."""
from app.models import VPNUser, Inbound, Node
from app.services.links import _host_for
from app.services.permissions import inbound_allowed


def export_profiles(users: list[VPNUser], inbounds: list[Inbound], nodes: dict[int, Node], host: str, format: str):
    profiles = []
    for user in users:
        if user.status != "active":
            continue
        for inbound in inbounds:
            if not inbound.is_active or not inbound_allowed(user, inbound.id):
                continue
            address = _host_for(inbound, nodes.get(inbound.node_id), host)
            name = f"{inbound.remark} | {user.username} | {inbound.id}"
            if format == "singbox":
                if inbound.network == "xhttp":
                    continue
                outbound = {"type": inbound.protocol, "tag": name, "server": address, "server_port": inbound.port}
                if inbound.protocol in {"vless", "vmess"}:
                    outbound["uuid"] = user.uuid
                    if inbound.protocol == "vmess":
                        outbound["security"] = "auto"
                    elif inbound.flow and inbound.network == "tcp":
                        outbound["flow"] = inbound.flow
                else:
                    outbound["password"] = user.password
                    if inbound.protocol == "shadowsocks":
                        outbound["method"] = "chacha20-ietf-poly1305"
                if inbound.security != "none":
                    tls = {"enabled": True, "server_name": inbound.sni or inbound.host or address}
                    if inbound.alpn:
                        tls["alpn"] = [p.strip() for p in inbound.alpn.split(",") if p.strip()]
                    if inbound.security == "reality":
                        tls["utls"] = {"enabled": True, "fingerprint": inbound.fingerprint or "chrome"}
                        tls["reality"] = {"enabled": True, "public_key": inbound.reality_public_key, "short_id": inbound.reality_short_id or ""}
                    outbound["tls"] = tls
                if inbound.network == "ws":
                    outbound["transport"] = {"type": "ws", "path": inbound.path or "/", "headers": {"Host": inbound.host or inbound.sni or address}}
                elif inbound.network == "grpc":
                    outbound["transport"] = {"type": "grpc", "service_name": inbound.service_name or inbound.tag}
                elif inbound.network == "httpupgrade":
                    outbound["transport"] = {"type": "httpupgrade", "path": inbound.path or "/", "host": inbound.host or inbound.sni or address}
                profiles.append(outbound)
                continue

            stream = {"network": inbound.network, "security": inbound.security}
            if inbound.network == "ws":
                stream["wsSettings"] = {"path": inbound.path or "/", "headers": {"Host": inbound.host or inbound.sni or address}}
            elif inbound.network == "grpc":
                stream["grpcSettings"] = {"serviceName": inbound.service_name or inbound.tag}
            elif inbound.network in {"xhttp", "httpupgrade"}:
                stream[f"{inbound.network}Settings"] = {"path": inbound.path or "/", "host": inbound.host or inbound.sni or address}
                if inbound.network == "xhttp":
                    stream["xhttpSettings"]["mode"] = "auto"
            if inbound.security == "tls":
                stream["tlsSettings"] = {"serverName": inbound.sni or inbound.host or address, "fingerprint": inbound.fingerprint or "chrome"}
                if inbound.alpn:
                    stream["tlsSettings"]["alpn"] = [p.strip() for p in inbound.alpn.split(",") if p.strip()]
            elif inbound.security == "reality":
                stream["realitySettings"] = {"serverName": inbound.sni, "fingerprint": inbound.fingerprint or "chrome", "publicKey": inbound.reality_public_key, "shortId": inbound.reality_short_id or ""}
            if inbound.protocol in {"vless", "vmess"}:
                identity = {"id": user.uuid, "encryption": "none"} if inbound.protocol == "vless" else {"id": user.uuid, "security": "auto"}
                if inbound.protocol == "vless" and inbound.flow and inbound.network == "tcp":
                    identity["flow"] = inbound.flow
                settings = {"vnext": [{"address": address, "port": inbound.port, "users": [identity]}]}
            else:
                server = {"address": address, "port": inbound.port, "password": user.password}
                if inbound.protocol == "shadowsocks":
                    server["method"] = "chacha20-ietf-poly1305"
                settings = {"servers": [server]}
            profiles.append({"remarks": name, "log": {"loglevel": "warning"}, "inbounds": [{"tag": "socks", "port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}], "outbounds": [{"tag": "proxy", "protocol": inbound.protocol, "settings": settings, "streamSettings": stream}]})
    if format == "singbox":
        if not profiles:
            return None
        return {"log": {"level": "warn"}, "inbounds": [{"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080}], "outbounds": [{"type": "selector", "tag": "SpecterGate", "outbounds": [p["tag"] for p in profiles]}, *profiles], "route": {"final": "SpecterGate"}}
    return profiles
