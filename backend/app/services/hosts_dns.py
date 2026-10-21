from __future__ import annotations

import ipaddress
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models import Node
from app.services.settings import get_setting, set_setting


class HostEntry(BaseModel):
    domain: str = Field(..., max_length=255)
    ips: list[str] = Field(..., min_length=1, max_length=20)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or len(v) > 255:
            raise ValueError("دامنه نامعتبر است.")
        return v

    @field_validator("ips")
    @classmethod
    def validate_ips(cls, values: list[str]) -> list[str]:
        cleaned = []
        for val in values:
            val = val.strip()
            try:
                ipaddress.ip_address(val)
            except ValueError:
                if not re.fullmatch(r"([a-z0-9_-]+\.)+[a-z]{2,}", val.lower()):
                    raise ValueError(f"آدرس IP یا دامنه نامعتبر است: {val}")
            cleaned.append(val)
        return cleaned


class DnsConfig(BaseModel):
    servers: list[str] = Field(
        default_factory=lambda: [
            "https://1.1.1.1/dns-query",
            "1.1.1.1",
            "8.8.8.8",
            "localhost",
        ],
        max_length=50,
    )
    hosts: list[HostEntry] = Field(default_factory=list, max_length=500)
    query_strategy: Literal["UseIP", "UseIPv4", "UseIPv6"] = "UseIP"
    disable_cache: bool = False
    disable_fallback: bool = False
    client_ip: str | None = None
    tag: str = "dns"

    @field_validator("servers")
    @classmethod
    def validate_servers(cls, servers: list[str]) -> list[str]:
        cleaned = []
        for s in servers:
            s = s.strip()
            if not s:
                continue
            # Allow: IP, localhost, https://... (DoH), tls://... (DoT), tcp+local://..., domain:port
            if s == "localhost":
                cleaned.append(s)
                continue
            if s.startswith(("https://", "tls://", "tcp://", "udp://", "tcp+local://", "udp+local://")):
                cleaned.append(s)
                continue
            # Check ip or ip:port
            target = s.split(":", 1)[0]
            try:
                ipaddress.ip_address(target)
                cleaned.append(s)
            except ValueError:
                if re.fullmatch(r"([a-z0-9_-]+\.)+[a-z]{2,}(:\d+)?", s.lower()):
                    cleaned.append(s)
                else:
                    raise ValueError(f"فرمت سرور DNS نامعتبر است: {s}")
        if not cleaned:
            cleaned = ["1.1.1.1", "8.8.8.8", "localhost"]
        return cleaned


def _dns_setting_key(node_id: int | None = None) -> str:
    return f"dns_config_node_{node_id}" if node_id else "dns_config_global"


def get_dns_config(db: Session, node_id: int | None = None) -> DnsConfig:
    key = _dns_setting_key(node_id)
    raw = get_setting(db, key, None)
    if not raw:
        # Fallback to global if node-specific is not set
        if node_id is not None:
            raw = get_setting(db, "dns_config_global", None)
    if not raw:
        return DnsConfig()
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return DnsConfig.model_validate(data)
    except Exception:
        return DnsConfig()


def save_dns_config(db: Session, config: DnsConfig, node_id: int | None = None) -> DnsConfig:
    key = _dns_setting_key(node_id)
    payload = config.model_dump()
    set_setting(db, key, payload)
    return config


def apply_dns_to_xray(db: Session, xray_config: dict, node: Node | None = None) -> None:
    node_id = node.id if node is not None and not node.is_local else None
    cfg = get_dns_config(db, node_id)

    dns_dict = {
        "tag": cfg.tag or "dns",
        "queryStrategy": cfg.query_strategy,
        "disableCache": cfg.disable_cache,
        "disableFallback": cfg.disable_fallback,
        "servers": cfg.servers,
        "hosts": {},
    }
    for h in cfg.hosts:
        if len(h.ips) == 1:
            dns_dict["hosts"][h.domain] = h.ips[0]
        else:
            dns_dict["hosts"][h.domain] = h.ips
    if cfg.client_ip:
        dns_dict["clientIp"] = cfg.client_ip

    xray_config["dns"] = dns_dict
