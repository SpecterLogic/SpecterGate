from __future__ import annotations

import base64
import json
import secrets
import struct
import zlib
import ipaddress
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.models import VPNUser, AmneziaPeer
from app.services import vault, amnezia_runtime
from fastapi import HTTPException
from app.services.settings import get_setting, set_setting


class AmneziaWgParams(BaseModel):
    enabled: bool = True
    port: int = Field(default=51821, ge=1, le=65535)
    server_address: str = Field(default="10.89.0.1/24")
    jc: int = Field(default=4, ge=1, le=128)
    jmin: int = Field(default=50, ge=40, le=1280)
    jmax: int = Field(default=1000, ge=40, le=1280)
    s1: int = Field(default=56, ge=15, le=1280)
    s2: int = Field(default=56, ge=15, le=1280)
    h1: int = Field(default=1234567890, ge=1, le=4294967295)
    h2: int = Field(default=987654321, ge=1, le=4294967295)
    h3: int = Field(default=1122334455, ge=1, le=4294967295)
    h4: int = Field(default=554433221, ge=1, le=4294967295)

    @model_validator(mode="after")
    def validate_network_and_headers(self):
        if self.server_address != "10.89.0.1/24":
            raise ValueError("The native AWG address pool is fixed at 10.89.0.1/24.")
        if len({self.h1, self.h2, self.h3, self.h4}) != 4:
            raise ValueError("AWG headers must be distinct.")
        if self.jmax < self.jmin:
            raise ValueError("Jmax must be at least Jmin.")
        return self

    @field_validator("jmax")
    @classmethod
    def validate_jmax(cls, v: int, info) -> int:
        jmin = info.data.get("jmin", 40)
        if v < jmin:
            raise ValueError("Jmax نمی‌تواند کمتر از Jmin باشد.")
        return v


def randomize_params(existing: AmneziaWgParams | None = None) -> AmneziaWgParams:
    headers = set()
    while len(headers) < 4:
        headers.add(secrets.randbelow(4000000000) + 1000000)
    h1, h2, h3, h4 = list(headers)
    jmin = secrets.randbelow(30) + 40
    jmax = secrets.randbelow(500) + 500
    s1 = secrets.randbelow(60) + 20
    s2 = secrets.randbelow(60) + 20
    jc = secrets.randbelow(6) + 3

    port = existing.port if existing else 51821
    server_address = existing.server_address if existing else "10.89.0.1/24"
    return AmneziaWgParams(
        enabled=True,
        port=port,
        server_address=server_address,
        jc=jc,
        jmin=jmin,
        jmax=jmax,
        s1=s1,
        s2=s2,
        h1=h1,
        h2=h2,
        h3=h3,
        h4=h4,
    )


def get_amnezia_params(db: Session) -> AmneziaWgParams:
    raw = get_setting(db, "amneziawg_params", None)
    if not raw:
        default_params = randomize_params()
        save_amnezia_params(db, default_params)
        return default_params
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return AmneziaWgParams.model_validate(data)
    except (ValueError, TypeError):
        raise HTTPException(409, "Stored AWG parameters are invalid; reset them before exporting.") from None


def save_amnezia_params(db: Session, params: AmneziaWgParams) -> AmneziaWgParams:
    set_setting(db, "amneziawg_params", params.model_dump())
    return params


def client_awg_config(db: Session, user: VPNUser, endpoint: str | None = None) -> str:
    params = get_amnezia_params(db)
    server_info = amnezia_runtime.server_status()
    if not params.enabled or not server_info.get("ready"):
        raise ValueError("Native AmneziaWG is not ready; install deploy/amneziawg_install.sh first.")
    if server_info.get("params") != params.model_dump():
        raise ValueError("AmneziaWG parameters are synchronizing; retry shortly.")
    peer = db.query(AmneziaPeer).filter_by(user_id=user.id, is_active=True).first()
    if not peer or user.status != "active":
        raise ValueError("AmneziaWG access must be granted to this active user first.")
    private = vault.get_secret(db, f"amnezia_peer_{peer.id}")
    if not private:
        raise ValueError("کلید خصوصی WireGuard برای این کاربر یافت نشد.")

    # Get server public key
    server_public_key = server_info["public_key"]

    host = endpoint or settings.public_host
    try:
        address = ipaddress.ip_address(host)
        host = f"[{address}]" if address.version == 6 else str(address)
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.split(".")):
            raise ValueError("Invalid endpoint host.") from None

    config_lines = [
        "[Interface]",
        f"PrivateKey = {private}",
        f"Address = {peer.address}/32",
        "DNS = 1.1.1.1, 1.0.0.1",
        "MTU = 1280",
        f"Jc = {params.jc}",
        f"Jmin = {params.jmin}",
        f"Jmax = {params.jmax}",
        f"S1 = {params.s1}",
        f"S2 = {params.s2}",
        f"H1 = {params.h1}",
        f"H2 = {params.h2}",
        f"H3 = {params.h3}",
        f"H4 = {params.h4}",
        "",
        "[Peer]",
        f"PublicKey = {server_public_key}",
        "AllowedIPs = 0.0.0.0/0",
        f"Endpoint = {host}:{params.port}",
        "PersistentKeepalive = 25",
        "",
    ]
    return "\n".join(config_lines)


def client_amnezia_vpn_payload(db: Session, user: VPNUser, endpoint: str | None = None) -> dict[str, Any]:
    raw_conf = client_awg_config(db, user, endpoint)
    params = get_amnezia_params(db)
    host = endpoint or settings.public_host
    return {
        "containers": [
            {
                "container": "amnezia-awg",
                "awg": {
                    "last_config": raw_conf,
                    "port": params.port,
                    "transport_proto": "udp",
                },
            }
        ],
        "defaultContainer": "amnezia-awg",
        "description": f"SpecterGate AWG - {user.username}",
        "dns1": "1.1.1.1",
        "dns2": "1.0.0.1",
        "hostName": host,
    }


def client_amnezia_vpn_uri(db: Session, user: VPNUser, endpoint: str | None = None) -> str:
    payload = client_amnezia_vpn_payload(db, user, endpoint)
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    compressed = struct.pack(">I", len(json_bytes)) + zlib.compress(json_bytes, 8)
    encoded = base64.urlsafe_b64encode(compressed).decode("utf-8").rstrip("=")
    return f"vpn://{encoded}"


def server_awg_config(db: Session) -> str:
    # The server private key stays root-owned; never export an unusable template
    # or expose it to delegated inbound administrators.
    raise HTTPException(409, "Native AWG is managed by the root companion; use the installer and per-user grants.")

