"""Xray-core configuration generation, validation, process control and stats sync."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import re
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from threading import RLock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Inbound, Node, TrafficSample, VPNUser
from app.services.permissions import inbound_allowed
from app.services.inbound_options import client_flow, apply_stream_options, options


_process: subprocess.Popen | None = None
_control_lock = RLock()


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _control_lock:
            return function(*args, **kwargs)
    return wrapped


def generate_keypair() -> dict[str, str]:
    private_key = X25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_b64 = base64.urlsafe_b64encode(private_raw).decode().rstrip("=")
    public_b64 = base64.urlsafe_b64encode(public_raw).decode().rstrip("=")
    return {
        "private_key": private_b64,
        "public_key": public_b64,
        "short_id": secrets.token_hex(4),
    }


def public_key_for(private: str) -> str:
    if not isinstance(private, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', private):
        raise ValueError('Invalid Reality private key encoding.')
    raw = base64.urlsafe_b64decode(private + '=' * (-len(private) % 4))
    key = X25519PrivateKey.from_private_bytes(raw)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.urlsafe_b64encode(public).decode().rstrip('=')


def _binary_path() -> str | None:
    candidate = settings.xray_binary
    if Path(candidate).exists():
        return str(Path(candidate))
    return shutil.which(candidate)


def _stream_settings(inbound: Inbound) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    network = inbound.network
    security = inbound.security

    if network == "ws":
        stream = {
            "network": "ws",
            "wsSettings": {
                "path": inbound.path or "/",
                "host": inbound.host or inbound.sni or "",
            },
        }
    elif network == "grpc":
        stream = {
            "network": "grpc",
            "grpcSettings": {"serviceName": inbound.service_name or inbound.tag, "multiMode": False},
        }
    elif network == "xhttp":
        stream = {"network": "xhttp", "xhttpSettings": {"path": inbound.path or "/", "host": inbound.host or "", "mode": "auto"}}
    elif network == "httpupgrade":
        stream = {
            "network": "httpupgrade",
            "httpupgradeSettings": {
                "path": inbound.path or "/",
                "host": inbound.host or inbound.sni or "",
            },
        }
    elif network == 'kcp':
        stream = {'network': 'kcp'}
    else:
        stream = {"network": "tcp", "tcpSettings": {"header": {"type": "none"}}}

    if security == "reality":
        if not inbound.reality_private_key:
            warnings.append(f"اینباند «{inbound.tag}»: کلید خصوصی Reality تنظیم نشده است.")
        dest = inbound.reality_dest or "www.cloudflare.com:443"
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "show": False,
            "dest": dest,
            "xver": 0,
            "serverNames": [inbound.sni or dest.split(":")[0]],
            "privateKey": inbound.reality_private_key or "",
            "shortIds": [inbound.reality_short_id or ""],
        }
    elif security == "tls":
        if not (inbound.tls_cert_path and inbound.tls_key_path):
            warnings.append(f"اینباند «{inbound.tag}»: مسیر گواهی TLS کامل نیست.")
        tls_settings: dict = {
            "serverName": inbound.sni or inbound.host or "",
            "alpn": [part.strip() for part in (inbound.alpn or "h2,http/1.1").split(",") if part.strip()],
        }
        if inbound.tls_cert_path and inbound.tls_key_path:
            tls_settings["certificates"] = [
                {
                    "certificateFile": inbound.tls_cert_path,
                    "keyFile": inbound.tls_key_path,
                }
            ]
        stream["security"] = "tls"
        stream["tlsSettings"] = tls_settings
    else:
        stream["security"] = "none"

    apply_stream_options(inbound, stream)
    return stream, warnings


def _clients_for(inbound: Inbound, users: list[VPNUser]) -> list[dict]:
    clients: list[dict] = []
    for user in users:
        if inbound.protocol in {"vless", "vmess"}:
            client: dict = {
                "id": user.uuid,
                "email": user.uuid,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": "",
                "subId": user.sub_token[:16],
                "reset": 0,
            }
            if inbound.protocol == "vless" and inbound.network == "tcp" and client_flow(inbound):
                client["flow"] = client_flow(inbound)
            clients.append(client)
        elif inbound.protocol == "trojan":
            clients.append({"password": user.password, "email": user.uuid})
        elif inbound.protocol == "shadowsocks":
            clients.append({"password": user.password, "email": user.uuid, "method": "chacha20-ietf-poly1305"})
    return clients


def _build_inbound(inbound: Inbound, users: list[VPNUser]) -> tuple[dict | None, list[str]]:
    users = [user for user in users if user.status == "active" and inbound_allowed(user, inbound.id)]
    clients = _clients_for(inbound, users)
    warnings: list[str] = []

    if inbound.protocol == "vless":
        settings_block = {"clients": clients, "decryption": "none", "fallbacks": []}
    elif inbound.protocol == "vmess":
        settings_block = {"clients": clients}
    elif inbound.protocol == "trojan":
        settings_block = {"clients": clients, "fallbacks": []}
    elif inbound.protocol == "shadowsocks":
        settings_block = {"clients": clients, "network": "tcp,udp"}
    else:
        return None, [f"پروتکل ناشناخته: {inbound.protocol}"]

    if inbound.security == "reality" and inbound.protocol != "vless":
        return None, [f"اینباند «{inbound.tag}»: Reality فقط برای VLESS پشتیبانی می‌شود."]

    stream, stream_warnings = _stream_settings(inbound)
    warnings.extend(stream_warnings)
    config = {
        "tag": inbound.tag,
        "listen": inbound.listen or "0.0.0.0",
        "port": inbound.port,
        "protocol": inbound.protocol,
        "settings": settings_block,
        "streamSettings": stream,
        "sniffing": options(inbound).sniffing.model_dump(),
    }
    return config, warnings


def generate_config(
    db: Session, node: Node | None = None
) -> tuple[dict, list[str], list[Inbound], int]:
    """Build a complete config for the local core or for one remote node agent.

    ``node=None`` selects local inbounds (local node or unassigned). Passing a
    node produces only the inbounds assigned to that node, which the agent
    endpoint serves for pull-based deployment.
    """
    if node is None:
        local_nodes = db.query(Node).filter(Node.is_local.is_(True)).all()
        local_node_ids = [item.id for item in local_nodes]
        filter_clause = Inbound.node_id.is_(None)
        if local_node_ids:
            filter_clause = or_(filter_clause, Inbound.node_id.in_(local_node_ids))
    else:
        filter_clause = Inbound.node_id == node.id

    inbounds = (
        db.query(Inbound)
        .filter(Inbound.is_active.is_(True), filter_clause)
        .order_by(Inbound.id.asc())
        .all()
    )
    inbounds = [ib for ib in inbounds if ib.is_usable]
    users = db.query(VPNUser).order_by(VPNUser.id.asc()).all()

    generated: list[dict] = []
    warnings: list[str] = []
    for inbound in inbounds:
        item, inbound_warnings = _build_inbound(inbound, users)
        warnings.extend(inbound_warnings)
        if item:
            generated.append(item)

    if node is not None:
        api_port = node.api_port or 10085
        log_settings: dict = {"loglevel": "warning"}
    else:
        try:
            api_port = int(settings.xray_api_address.rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            api_port = 10085
        log_settings = {
            "loglevel": "warning",
            "access": "none",
            "error": str(Path(settings.xray_log_path).resolve()),
        }

    config = {
        "log": log_settings,
        "api": {"tag": "api", "services": ["StatsService", "HandlerService", "RoutingService"]},
        "stats": {},
        "policy": {
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True,
                    "statsUserOnline": True,
                }
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
            },
        },
        "inbounds": [
            {
                "tag": "api",
                "listen": "127.0.0.1",
                "port": api_port,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
            },
            *generated,
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {}},
            {"tag": "blocked", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"},
            ],
        },
    }
    client_count = sum(len(item.get("settings", {}).get("clients", [])) for item in generated)
    from app.services.routing import apply_to_xray
    apply_to_xray(db, config, node)
    from app.services.hosts_dns import apply_dns_to_xray
    apply_dns_to_xray(db, config, node)
    return config, warnings, inbounds, client_count


def config_hash(config: dict) -> str:
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_config(config: dict) -> Path:
    path = Path(settings.xray_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(config, ensure_ascii=False, indent=2)
    fd, temp_path = tempfile.mkstemp(prefix="spectergate-xray-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return path


def validate_config(path: Path) -> tuple[bool, str]:
    binary = _binary_path()
    if not binary:
        return False, "باینری Xray پیدا نشد؛ فایل کانفیگ نوشته شد اما اعتبارسنجی انجام نشد."
    commands = [
        [binary, "run", "-test", "-c", str(path)],
        [binary, "-test", "-config", str(path)],
    ]
    last_output = ""
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            last_output = (result.stdout or "") + (result.stderr or "")
            if result.returncode == 0:
                return True, last_output.strip() or "کانفیگ معتبر است."
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_output = str(exc)
    return False, last_output.strip() or "اعتبارسنجی کانفیگ ناموفق بود."


@serialized
def apply_config(db: Session, restart: bool = True) -> dict:
    if _process is not None and _process.poll() is None:
        sync_stats(db)
    config, warnings, inbounds, client_count = generate_config(db)
    path = Path(settings.xray_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, candidate = tempfile.mkstemp(prefix="spectergate-validate-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False)
        valid, validation_output = validate_config(Path(candidate))
    finally:
        Path(candidate).unlink(missing_ok=True)
    message = "کانفیگ ساخته شد."
    if warnings:
        message += " هشدار: " + " ".join(warnings)
    if not valid:
        message += " " + validation_output
        return {
            "ok": False,
            "message": message,
            "config_path": str(path),
            "inbound_count": len(inbounds),
            "client_count": client_count,
            "validation_output": validation_output,
            "warnings": warnings,
        }
    if restart:
        path = write_config(config)
        try:
            restart_process()
            from app.services import session_control
            import grpc
            try:
                session_control.sync(db)
            except (grpc.RpcError, RuntimeError):
                warnings.append("Targeted session control unavailable; install the managed SpecterGate core.")
            message += " سرویس Xray راه‌اندازی مجدد شد."
        except RuntimeError as exc:
            message += f" اما اجرای Xray ناموفق بود: {exc}"
            return {
                "ok": False,
                "message": message,
                "config_path": str(path),
                "inbound_count": len(inbounds),
                "client_count": client_count,
                "validation_output": validation_output,
                "warnings": warnings,
            }
    else:
        path = write_config(config)
    return {
        "ok": True,
        "message": message,
        "config_path": str(path),
        "inbound_count": len(inbounds),
        "client_count": client_count,
        "validation_output": validation_output,
        "warnings": warnings,
    }


def xray_status() -> dict:
    binary = _binary_path()
    config_path = Path(settings.xray_config_path)
    running = _process is not None and _process.poll() is None
    pid = _process.pid if running and _process else None
    if not settings.xray_enabled:
        message = "مدیریت Xray در تنظیمات غیرفعال است."
    elif not binary:
        message = "باینری Xray نصب نیست. کانفیگ را می‌توانید تولید کنید، اما اجرا نیاز به نصب Xray دارد."
    elif running:
        message = "پروسه Xray توسط پنل اجرا شده و در حال کار است."
    else:
        message = "Xray توسط پنل اجرا نشده است؛ ممکن است به‌صورت سرویس سیستمی اجرا شود."
    return {
        "enabled": settings.xray_enabled,
        "binary_available": bool(binary),
        "running": running,
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "message": message,
        "pid": pid,
    }


@serialized
def start_process() -> None:
    global _process
    if not settings.xray_enabled:
        raise RuntimeError("مدیریت Xray غیرفعال است.")
    if _process is not None and _process.poll() is None:
        return
    binary = _binary_path()
    if not binary:
        raise RuntimeError("باینری Xray نصب نیست.")
    config_path = Path(settings.xray_config_path).resolve()
    if not config_path.exists():
        raise RuntimeError("فایل کانفیگ وجود ندارد؛ ابتدا کانفیگ را اعمال کنید.")
    log_path = Path(settings.xray_log_path).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        _process = subprocess.Popen(
            [binary, "run", "-c", str(config_path)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(config_path.parent),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        log_handle.close()
    try:
        code = _process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        return
    raise RuntimeError(f'Xray exited during startup (code {code}); inspect the core log.')


@serialized
def stop_process() -> None:
    global _process
    if _process is None or _process.poll() is not None:
        _process = None
        return
    _process.terminate()
    try:
        _process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        _process.kill()
    _process = None


@serialized
def restart_process() -> None:
    stop_process()
    start_process()


@serialized
def sync_stats(db: Session) -> dict:
    binary = _binary_path()
    if not binary:
        return {"ok": False, "message": "باینری Xray نصب نیست.", "users": 0, "samples": 0}
    command = [
        binary,
        "api",
        "statsquery",
        f"--server={settings.xray_api_address}",
        "-pattern",
        "",
        "-reset",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "message": f"خطا در ارتباط با Xray: {exc}", "users": 0, "samples": 0}
    if result.returncode != 0:
        return {
            "ok": False,
            "message": (result.stderr or result.stdout or "Xray API در دسترس نیست.").strip(),
            "users": 0,
            "samples": 0,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "message": "پاسخ Xray API قابل خواندن نبود.", "users": 0, "samples": 0}

    stats = payload.get("stat", payload.get("stats", []))
    users = {user.uuid: user for user in db.query(VPNUser).all()}
    inbounds = {inbound.tag: inbound for inbound in db.query(Inbound).all()}
    touched: dict[VPNUser, dict[str, int]] = {}
    inbound_traffic: dict[Inbound, dict[str, int]] = {}

    for item in stats:
        name = str(item.get("name", ""))
        try:
            value = int(item.get("value", 0))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        parts = name.split(">>>")
        if len(parts) != 4:
            continue
        kind, identifier, _, direction = parts
        if kind == "user" and identifier in users:
            user = users[identifier]
            bucket = touched.setdefault(user, {"upload": 0, "download": 0})
            if direction == "uplink":
                bucket["upload"] += value
            elif direction == "downlink":
                bucket["download"] += value
        elif kind == "inbound" and identifier in inbounds:
            inbound = inbounds[identifier]
            bucket = inbound_traffic.setdefault(inbound, {"upload": 0, "download": 0})
            if direction == "uplink":
                bucket["upload"] += value
            elif direction == "downlink":
                bucket["download"] += value

    now = datetime.now(timezone.utc)
    samples = 0
    for user, bucket in touched.items():
        db.execute(update(VPNUser).where(VPNUser.id == user.id).values(upload_bytes=VPNUser.upload_bytes + bucket["upload"], download_bytes=VPNUser.download_bytes + bucket["download"]))
        db.add(
            TrafficSample(
                user_id=user.id,
                upload_bytes=bucket["upload"],
                download_bytes=bucket["download"],
                recorded_at=now,
            )
        )
        samples += 1
    for inbound, bucket in inbound_traffic.items():
        inbound.upload_bytes = int(inbound.upload_bytes or 0) + bucket["upload"]
        inbound.download_bytes = int(inbound.download_bytes or 0) + bucket["download"]
    db.commit()
    return {
        "ok": True,
        "message": f"آمار {len(touched)} کاربر به‌روزرسانی شد.",
        "users": len(touched),
        "samples": samples,
    }
