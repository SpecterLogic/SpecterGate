from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin, Inbound, Node
from app.schemas import OperationResult
from app.services.audit import write_audit
from app.services.external_protocols import (
    generate_hysteria2_client_uri,
    generate_hysteria2_outbound,
    generate_mtproto_fake_tls_secret,
    generate_mtproto_link,
    generate_shadowtls_outbound,
    generate_tuic_client_uri,
    generate_tuic_outbound,
)
from app.services.settings import get_setting, set_setting

router = APIRouter(prefix="/protocols", tags=["protocols"])
read_access = require_permission("inbounds.read")
write_access = require_permission("inbounds.manage")


class Hysteria2ConfigRequest(BaseModel):
    server: str
    port: int = Field(default=8443, ge=1, le=65535)
    password: str
    sni: str = "www.bing.com"
    obfs_password: str | None = None
    insecure: bool = False
    remark: str = "SpecterGate-Hy2"


class TuicConfigRequest(BaseModel):
    server: str
    port: int = Field(default=8443, ge=1, le=65535)
    uuid: str
    password: str
    sni: str = "www.bing.com"
    congestion_control: str = "bbr"
    remark: str = "SpecterGate-TUIC"


class TgSecretRequest(BaseModel):
    domain: str = "www.cloudflare.com"


@router.get("/overview")
def get_protocols_overview(_: Admin = Depends(read_access)):
    return {
        "native_protocols": [
            {"id": "vless", "name": "VLESS (Reality / TLS / RAW / XHTTP)", "status": "active", "native": True},
            {"id": "vmess", "name": "VMess (WS / gRPC / TCP)", "status": "active", "native": True},
            {"id": "trojan", "name": "Trojan (TLS / gRPC)", "status": "active", "native": True},
            {"id": "shadowsocks", "name": "Shadowsocks (AEAD 2022)", "status": "active", "native": True},
            {"id": "amneziawg", "name": "AmneziaWG (Advanced JUNK/Opaque)", "status": "active", "native": True},
            {"id": "wireguard", "name": "Standard WireGuard & CF WARP", "status": "active", "native": True},
        ],
        "extended_families": [
            {"id": "hysteria2", "name": "Hysteria 2 (QUIC / Brutal Congestion)", "status": "ready", "client_formats": ["URI", "Sing-box", "Clash-Meta"]},
            {"id": "tuic", "name": "TUIC v5 (QUIC 0-RTT / BBR)", "status": "ready", "client_formats": ["URI", "Sing-box"]},
            {"id": "shadowtls", "name": "ShadowTLS v3 (Handshake Camouflage)", "status": "ready", "client_formats": ["Sing-box", "Clash-Meta"]},
            {"id": "telegram", "name": "Telegram MTProto Proxy (Fake-TLS)", "status": "ready", "client_formats": ["tg://proxy", "https://t.me/proxy"]},
        ],
    }


@router.post("/hysteria2/generate")
def create_hysteria2_config(payload: Hysteria2ConfigRequest, _: Admin = Depends(read_access)):
    uri = generate_hysteria2_client_uri(
        server=payload.server,
        port=payload.port,
        password=payload.password,
        sni=payload.sni,
        obfs_password=payload.obfs_password,
        insecure=payload.insecure,
        remark=payload.remark,
    )
    outbound = generate_hysteria2_outbound(
        server=payload.server,
        port=payload.port,
        password=payload.password,
        sni=payload.sni,
        obfs_password=payload.obfs_password,
        insecure=payload.insecure,
    )
    return {
        "uri": uri,
        "singbox_outbound": outbound,
        "clash_meta_outbound": outbound,
    }


@router.post("/tuic/generate")
def create_tuic_config(payload: TuicConfigRequest, _: Admin = Depends(read_access)):
    uri = generate_tuic_client_uri(
        server=payload.server,
        port=payload.port,
        uuid_str=payload.uuid,
        password=payload.password,
        sni=payload.sni,
        congestion_control=payload.congestion_control,
        remark=payload.remark,
    )
    outbound = generate_tuic_outbound(
        server=payload.server,
        port=payload.port,
        uuid_str=payload.uuid,
        password=payload.password,
        sni=payload.sni,
        congestion_control=payload.congestion_control,
    )
    return {
        "uri": uri,
        "singbox_outbound": outbound,
    }


@router.post("/telegram/secret")
def generate_tg_secret(payload: TgSecretRequest, _: Admin = Depends(read_access)):
    secret = generate_mtproto_fake_tls_secret(domain=payload.domain)
    return {"domain": payload.domain, "secret": secret}


@router.get("/telegram/link")
def get_tg_link(
    server: str = Query(..., min_length=1),
    port: int = Query(default=443, ge=1, le=65535),
    secret: str = Query(..., min_length=16),
    _: Admin = Depends(read_access),
):
    link = generate_mtproto_link(server=server, port=port, secret=secret)
    return {"link": link, "tg_uri": link.replace("https://t.me/proxy", "tg://proxy")}
