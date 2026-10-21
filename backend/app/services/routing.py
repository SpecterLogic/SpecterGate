"""Node-specific Direct/WARP/Block routing with write-only WireGuard credentials."""
import base64
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from fastapi import HTTPException

from app.models import Inbound, Node
from app.services.settings import get_setting, set_setting
from app.services.vault import get_secret, put_secret, has_secret


def key32(value):
    try:
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError()
    except Exception:
        raise ValueError("WireGuard key must be a base64-encoded 32-byte key.") from None
    return value


class RoutingRule(BaseModel):
    outbound: str = Field(pattern=r"^(?:direct|warp|blocked|ipv4|proxy-[a-zA-Z0-9_-]{1,40})$")
    domains: list[str] = Field(default_factory=list, max_length=200)
    ips: list[str] = Field(default_factory=list, max_length=200)
    inbound_ids: list[int] = Field(default_factory=list, max_length=200)
    protocols: list[Literal['http', 'tls', 'quic', 'bittorrent']] = Field(default_factory=list, max_length=4)
    network: Literal['tcp', 'udp', 'tcp,udp'] | None = None
    port: str | None = Field(default=None, max_length=200)

    @field_validator('port')
    @classmethod
    def ports(cls, value):
        if value is None:
            return value
        for item in value.split(','):
            bounds = item.strip().split('-')
            if len(bounds) not in {1, 2} or any(not b.isdigit() or not 1 <= int(b) <= 65535 for b in bounds) or int(bounds[0]) > int(bounds[-1]):
                raise ValueError('Expected a port or range, e.g. 443 or 80,8000-9000.')
        return value

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, values):
        if any(not value or len(value) > 255 or any(ord(c) < 32 for c in value) for value in values):
            raise ValueError("Invalid routing domain.")
        return values

    @field_validator("ips")
    @classmethod
    def validate_ips(cls, values):
        for value in values:
            if value.startswith("geoip:") and re.fullmatch(r"geoip:[a-zA-Z0-9_!,-]+", value):
                continue
            ipaddress.ip_network(value, strict=False)
        return values

    @model_validator(mode="after")
    def conditions(self):
        if not (self.domains or self.ips or self.inbound_ids or self.protocols or self.network or self.port):
            raise ValueError("Each rule needs a domain, IP or inbound condition.")
        return self


class ProxyOutbound(BaseModel):
    tag: str = Field(pattern=r"^proxy-[a-zA-Z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=80)
    protocol: Literal["socks", "http"] = "socks"
    address: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=128)

    @field_validator("address")
    @classmethod
    def address_format(cls, value):
        try: return str(ipaddress.ip_address(value))
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", value):
                raise ValueError("Enter an IP or hostname without a scheme or port.")
            return value


class ProxyOutboundUpdate(ProxyOutbound):
    password: SecretStr | None = None


class RoutingConfig(BaseModel):
    default_outbound: str = Field(default="direct", pattern=r"^(?:direct|warp|blocked|ipv4|proxy-[a-zA-Z0-9_-]{1,40})$")
    outbounds: list[ProxyOutbound] = Field(default_factory=list, max_length=20)
    domain_strategy: Literal['AsIs', 'IPIfNonMatch', 'IPOnDemand'] = 'AsIs'
    block_bittorrent: bool = False
    block_ips: list[str] = Field(default_factory=list, max_length=200)
    block_domains: list[str] = Field(default_factory=list, max_length=200)
    direct_ips: list[str] = Field(default_factory=list, max_length=200)
    direct_domains: list[str] = Field(default_factory=list, max_length=200)
    ipv4_domains: list[str] = Field(default_factory=list, max_length=200)
    _ip_lists = field_validator('block_ips', 'direct_ips')(RoutingRule.validate_ips.__func__)
    _domain_lists = field_validator('block_domains', 'direct_domains', 'ipv4_domains')(RoutingRule.validate_domains.__func__)
    warp_enabled: bool = False
    warp_endpoint: str = "engage.cloudflareclient.com:2408"
    warp_public_key: str = ""
    warp_addresses: list[str] = Field(default_factory=lambda: ["172.16.0.2/32"], min_length=1, max_length=4)
    warp_reserved: list[int] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    warp_mtu: int = Field(default=1280, ge=1280, le=1500)
    rules: list[RoutingRule] = Field(default_factory=list, max_length=100)

    @field_validator("warp_endpoint")
    @classmethod
    def endpoint(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit("//" + value)
        try:
            valid = parsed.hostname and parsed.port and 1 <= parsed.port <= 65535
        except ValueError:
            valid = False
        if not valid or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or len(value) > 255:
            raise ValueError("Expected a WireGuard host:port endpoint.")
        return value

    @field_validator("warp_public_key")
    @classmethod
    def public_key(cls, value):
        return key32(value) if value else value

    @field_validator("warp_addresses")
    @classmethod
    def addresses(cls, values):
        for value in values:
            ipaddress.ip_interface(value)
        return values

    @field_validator("warp_reserved")
    @classmethod
    def reserved(cls, values):
        if any(not 0 <= v <= 255 for v in values):
            raise ValueError("Reserved values must be bytes.")
        return values

    @model_validator(mode="after")
    def enabled_routes(self):
        tags = [item.tag for item in self.outbounds]
        if len(tags) != len(set(tags)): raise ValueError("Outbound tags must be unique.")
        available = {"direct", "ipv4", "blocked", "warp", *tags}
        if self.default_outbound not in available or any(rule.outbound not in available for rule in self.rules):
            raise ValueError("The selected outbound does not exist; update its routing rules first.")
        if self.warp_enabled and not self.warp_public_key:
            raise ValueError("A peer public key is required for WARP.")
        if not self.warp_enabled and (self.default_outbound == "warp" or any(r.outbound == "warp" for r in self.rules)):
            raise ValueError("Enable WARP before selecting it as an outbound.")
        return self


class RoutingUpdate(RoutingConfig):
    warp_private_key: SecretStr | None = None


def profile_keys(node_id=None):
    suffix = str(node_id) if node_id is not None else "local"
    return "routing_" + suffix, "warp_private_" + suffix


def outbound_secret(tag, node_id=None):
    return f"proxy_password_{node_id if node_id is not None else 'local'}_{tag}"


def verify_node(db, node_id):
    node = db.get(Node, node_id) if node_id is not None else None
    if node_id is not None and (node is None or node.is_local):
        raise HTTPException(status_code=400, detail="نود راه دور معتبر انتخاب کنید؛ برای سرور محلی گزینه محلی را انتخاب کنید.")
    return node


def read_config(db, node_id=None):
    key, secret = profile_keys(node_id)
    stored = get_setting(db, key, None)
    values = RoutingConfig.model_validate(stored or {}).model_dump()
    values["outbounds"] = [{**item, "password_configured": has_secret(db, outbound_secret(item["tag"], node_id))} for item in values["outbounds"]]
    return {**values, "private_key_configured": has_secret(db, secret), "node_id": node_id}


def write_config(db, payload: RoutingUpdate, node_id=None):
    verify_node(db, node_id)
    key, secret = profile_keys(node_id)
    values = payload.model_dump(exclude={"warp_private_key"})
    if payload.warp_private_key is not None:
        try:
            private = key32(payload.warp_private_key.get_secret_value().strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="کلید خصوصی WireGuard معتبر نیست.") from None
        put_secret(db, secret, private)
        db.flush()
    if payload.warp_enabled and not has_secret(db, secret):
        raise HTTPException(status_code=400, detail="کلید خصوصی WARP لازم است.")
    for rule in payload.rules:
        for inbound_id in set(rule.inbound_ids):
            inbound = db.get(Inbound, inbound_id)
            node = db.get(Node, inbound.node_id) if inbound and inbound.node_id else None
            actual = node.id if node and not node.is_local else None
            if inbound is None or actual != node_id:
                raise HTTPException(status_code=400, detail="اینباند قانون باید متعلق به نود همین پروفایل باشد.")
    for item in payload.outbounds:
        if item.username and not has_secret(db, outbound_secret(item.tag, node_id)):
            raise HTTPException(status_code=400, detail="برای خروجی دارای نام کاربری، رمز را در بخش خروجی‌ها وارد کنید.")
    set_setting(db, key, values)


def apply_to_xray(db, config, node=None):
    node_id = node.id if node is not None and not node.is_local else None
    key, secret = profile_keys(node_id)
    policy = RoutingConfig.model_validate(get_setting(db, key, None) or {})
    config['routing']['domainStrategy'] = policy.domain_strategy
    config['outbounds'].append({'tag': 'ipv4', 'protocol': 'freedom', 'settings': {'domainStrategy': 'ForceIPv4'}})
    for item in policy.outbounds:
        server = {"address": item.address, "port": item.port}
        if item.username:
            password = get_secret(db, outbound_secret(item.tag, node_id))
            if password is None: raise RuntimeError("Proxy outbound credential unavailable.")
            server["users"] = [{"user": item.username, "pass": password}]
        config["outbounds"].append({"tag": item.tag, "protocol": item.protocol, "settings": {"servers": [server]}})
    if policy.warp_enabled:
        private = get_secret(db, secret)
        if private is None:
            raise RuntimeError("WARP private key is unavailable; restore the integration key.")
        warp = {"tag": "warp", "protocol": "wireguard", "settings": {"secretKey": private, "address": policy.warp_addresses, "mtu": policy.warp_mtu, "reserved": policy.warp_reserved, "noKernelTun": True, "peers": [{"publicKey": policy.warp_public_key, "endpoint": policy.warp_endpoint, "allowedIPs": ["0.0.0.0/0", "::/0"], "keepAlive": 25}]}}
        config["outbounds"].append(warp)
        if policy.default_outbound == "warp":
            config["outbounds"].remove(warp)
            config["outbounds"].insert(0, warp)
    if policy.default_outbound in {'ipv4', 'blocked'} or policy.default_outbound.startswith("proxy-"):
        outbound = next(o for o in config['outbounds'] if o.get('tag') == policy.default_outbound)
        config['outbounds'].remove(outbound)
        config['outbounds'].insert(0, outbound)
    if policy.block_bittorrent:
        config['routing']['rules'].append({'type': 'field', 'protocol': ['bittorrent'], 'outboundTag': 'blocked'})
    for attribute, field, outbound in [('block_ips', 'ip', 'blocked'), ('block_domains', 'domain', 'blocked'), ('direct_ips', 'ip', 'direct'), ('direct_domains', 'domain', 'direct'), ('ipv4_domains', 'domain', 'ipv4')]:
        values = getattr(policy, attribute)
        if values:
            config['routing']['rules'].append({'type': 'field', field: values, 'outboundTag': outbound})
    for item in policy.rules:
        rule = {"type": "field", "outboundTag": item.outbound}
        if item.domains:
            rule["domain"] = item.domains
        if item.ips:
            rule["ip"] = item.ips
        if item.protocols:
            rule['protocol'] = item.protocols
        if item.network:
            rule['network'] = item.network
        if item.port:
            rule['port'] = item.port
        if item.inbound_ids:
            tags = [i.tag for i in db.query(Inbound).filter(Inbound.id.in_(item.inbound_ids)).all()]
            if not tags:
                continue
            rule["inboundTag"] = tags
        config["routing"]["rules"].append(rule)


def redact_config(config):
    import copy
    result = copy.deepcopy(config)
    def walk(item):
        if isinstance(item, dict):
            for key, value in item.items():
                if key in {"secretKey", "privateKey", "password", "pass"}:
                    item[key] = "[redacted]"
                else:
                    walk(value)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(result)
    return result
