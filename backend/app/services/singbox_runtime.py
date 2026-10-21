"""Supervise a second engine; authenticated VLESS relay preserves Xray accounting/routing."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from app.config import settings
from app.models import Inbound, Node, VPNUser
from app.services import xray
from app.services.permissions import inbound_allowed
from app.services.inbound_options import options, client_sni, client_port
from app.services.settings import get_setting, set_setting

_process = None
_signature = None


def ss_key(user):
    return base64.b64encode(hashlib.sha256(user.password.encode()).digest()).decode()


def server_key(inbound):
    if options(inbound).ss_server_key:
        return options(inbound).ss_server_key
    # Separate per inbound, stable across restarts; never export the panel secret.
    return base64.b64encode(hmac.new(settings.secret_key.encode(), f"shadowtls:{inbound.id}".encode(), hashlib.sha256).digest()).decode()


def tls(inbound, client=False):
    if client:
        result = {"enabled": True, "server_name": client_sni(inbound) or ""}
        if inbound.security == "reality":
            result.update({"utls": {"enabled": True, "fingerprint": inbound.fingerprint or "chrome"}, "reality": {"enabled": True, "public_key": inbound.reality_public_key, "short_id": inbound.reality_short_id or ""}})
        return result
    if inbound.security == "reality":
        host, port = inbound.reality_dest.rsplit(":", 1)
        return {"enabled": True, "server_name": client_sni(inbound), "reality": {"enabled": True, "handshake": {"server": host, "server_port": int(port)}, "private_key": inbound.reality_private_key, "short_id": options(inbound).reality.shortIds or [inbound.reality_short_id or ""]}}
    if not inbound.tls_cert_path or not inbound.tls_key_path:
        raise ValueError(f"TLS certificate/key required for {inbound.tag}")
    return {"enabled": True, "server_name": inbound.sni or "", "certificate_path": inbound.tls_cert_path, "key_path": inbound.tls_key_path, "min_version": options(inbound).tls.minVersion, "max_version": options(inbound).tls.maxVersion}


def client_outbounds(inbound, user, host, name):
    protocol = inbound.protocol
    row = {"type": protocol, "tag": name, "server": host, "server_port": client_port(inbound)}
    if protocol == "shadowtls":
        row.update({"version": 3, "password": user.password, "tls": {"enabled": True, "server_name": options(inbound).shadowtls_handshake}})
        row["tag"] = name + "-tls"
        return [row, {"type": "shadowsocks", "tag": name, "server": host, "server_port": client_port(inbound), "method": "2022-blake3-aes-256-gcm", "password": server_key(inbound) + ":" + ss_key(user), "detour": row["tag"]}]
    if protocol in {"vless", "vmess", "tuic"}:
        row["uuid"] = user.uuid
    if protocol in {"trojan", "hysteria2", "tuic"}:
        row["password"] = user.password
    if protocol == "vmess":
        row.update({"security": "auto", "alter_id": 0})
    if protocol == "shadowsocks":
        row.update({"method": "2022-blake3-aes-256-gcm", "password": server_key(inbound) + ":" + ss_key(user)})
    if protocol == "vless" and inbound.flow:
        row["flow"] = inbound.flow
    if inbound.security != "none":
        row["tls"] = tls(inbound, True)
    if protocol == "tuic":
        row["congestion_control"] = "bbr"
    if inbound.network != "tcp":
        transport = {"type": inbound.network}
        if inbound.network in {"ws", "httpupgrade"}:
            transport.update({"path": inbound.path or "/", "headers": {"Host": inbound.host or host}})
        if inbound.network == "grpc":
            transport["service_name"] = inbound.service_name or ""
        row["transport"] = transport
    return [row]


def generate(db):
    nodes = {n.id: n for n in db.query(Node).all()}
    records = [ib for ib in db.query(Inbound).filter_by(engine="singbox").all() if ib.is_usable and (ib.node_id is None or nodes.get(ib.node_id) and nodes[ib.node_id].is_local)]
    users = [u for u in db.query(VPNUser).all() if u.status == "active"]
    inbounds, used_users = [], {}
    for ib in records:
        permitted = [u for u in users if inbound_allowed(u, ib.id)]
        if not permitted:
            continue  # An empty users list must never accidentally enable anonymous access.
        used_users.update({u.uuid: u for u in permitted})
        row = {"type": ib.protocol, "tag": ib.tag, "listen": ib.listen, "listen_port": ib.port}
        if ib.protocol in {"vless", "vmess", "tuic"}:
            row["users"] = [{"name": u.uuid, "uuid": u.uuid, **({"password": u.password} if ib.protocol == "tuic" else {}), **({"flow": ib.flow} if ib.protocol == "vless" and ib.flow else {})} for u in permitted]
        else:
            row["users"] = [{"name": u.uuid, "password": u.password} for u in permitted]
        if ib.protocol in {"shadowsocks", "shadowtls"}:
            inner = {"listen":"127.0.0.1","type": "shadowsocks", "tag": ib.tag + "-inner", "method": "2022-blake3-aes-256-gcm", "password": server_key(ib), "users": [{"name": u.uuid, "password": ss_key(u)} for u in permitted]}
            if ib.protocol == "shadowtls":
                row.update({"version": 3, "strict_mode": True, "handshake": {"server": options(ib).shadowtls_handshake, "server_port": options(ib).shadowtls_handshake_port}, "detour": inner["tag"]})
                inbounds.append(inner)
            else:
                row.update({k: v for k, v in inner.items() if k not in {"tag", "type", "listen"}})
        if ib.security != "none":
            row["tls"] = tls(ib)
        if ib.protocol == "tuic":
            row["congestion_control"] = "bbr"
        if ib.network != "tcp":
            transport = {"type": ib.network}
            if ib.network in {"ws", "httpupgrade"}:
                transport["path"] = ib.path or "/"
            if ib.network == "grpc":
                transport["service_name"] = ib.service_name or ""
            row["transport"] = transport
        inbounds.append(row)
    outbounds = [{"type": "vless", "tag": "relay-" + u.uuid, "server": "127.0.0.1", "server_port": settings.singbox_relay_port, "uuid": u.uuid} for u in used_users.values()]
    rules = [{"auth_user": [u.uuid], "action": "route", "outbound": "relay-" + u.uuid} for u in used_users.values()]
    return {"log": {"level": "warn"}, "inbounds": inbounds, "outbounds": outbounds, "route": {"rules": [*rules, {"action": "reject"}]}}


def status():
    return {"installed": bool(shutil.which(settings.singbox_binary)), "running": _process is not None and _process.poll() is None, "pid": _process.pid if _process and _process.poll() is None else None}


def stop():
    global _process, _signature
    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)
    _process, _signature = None, None


@xray.serialized
def apply(db):
    global _process, _signature
    binary = shutil.which(settings.singbox_binary)
    if not binary:
        raise RuntimeError("Install Sing-box 1.14.3 before applying this engine.")
    config = generate(db)
    signature = xray.config_hash(config)
    if status()["running"] and signature == _signature:
        return {"ok": True, "message": "Sing-box configuration is current."}
    if not config["inbounds"]:
        stop()
        return {"ok": True, "message": "No authorized active Sing-box inbounds; engine stopped."}
    path = Path(settings.singbox_config_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, candidate = tempfile.mkstemp(suffix=".json", prefix="validate-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(config, file)
        result = subprocess.run([binary, "check", "-c", candidate], capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError("Sing-box rejected the configuration. Check protocol, certificates and transport compatibility.")
        try:
            current = json.loads(Path(settings.xray_config_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not xray.xray_status()["running"] or xray.config_hash(current) != xray.config_hash(xray.generate_config(db)[0]):
            result = xray.apply_config(db)
            if not result["ok"]:
                raise RuntimeError("Xray routing/accounting relay could not be started.")
        stop()
        os.replace(candidate, path)
        os.chmod(path, 0o600)
        with path.with_suffix(".log").open("ab") as log:
            _process = subprocess.Popen([binary, "run", "-c", str(path)], stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            code = _process.wait(timeout=.4)
        except subprocess.TimeoutExpired:
            _signature = signature
            return {"ok": True, "message": "Sing-box started; traffic is routed and counted by the local Xray relay."}
        raise RuntimeError(f"Sing-box exited at startup ({code}); inspect its local log.")
    finally:
        Path(candidate).unlink(missing_ok=True)


def reconcile(db):
    if get_setting(db, "singbox_enabled", False):
        apply(db)
    else:
        stop()
