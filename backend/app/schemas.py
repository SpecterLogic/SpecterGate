from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------- Auth / admins ----------
class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    otp_code: str | None = Field(default=None, max_length=16)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_owner: bool = False
    is_active: bool
    totp_enabled: bool = False
    parent_id: int | None = None
    scope: str = "all"
    max_users: int | None = None
    traffic_quota_bytes: int | None = None
    credit: int = 0
    require_template: bool = False
    permissions: list[str] = []
    allowed_inbound_ids: list[int] | None = None
    user_count: int = 0
    used_traffic_bytes: int = 0
    last_login_at: datetime | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    admin: AdminOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=4, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Literal["superadmin", "admin", "reseller", "support", "viewer"] = "reseller"
    parent_id: int | None = None
    scope: Literal["all", "own", "none"] = "own"
    max_users: int | None = Field(default=None, ge=0)
    traffic_quota_bytes: int | None = Field(default=None, ge=0)
    credit: int = Field(default=0, ge=0)
    require_template: bool = False
    permissions: list[str] = Field(default_factory=list)
    is_active: bool = True
    allowed_inbound_ids: list[int] | None = Field(default=None, max_length=1000)


class AdminUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Literal["superadmin", "admin", "reseller", "support", "viewer"] | None = None
    parent_id: int | None = None
    scope: Literal["all", "own", "none"] | None = None
    max_users: int | None = Field(default=None, ge=0)
    traffic_quota_bytes: int | None = Field(default=None, ge=0)
    credit: int | None = Field(default=None, ge=0)
    require_template: bool | None = None
    permissions: list[str] | None = None
    is_active: bool | None = None
    allowed_inbound_ids: list[int] | None = Field(default=None, max_length=1000)


class CreditAdjustment(BaseModel):
    amount: int = Field(description="مثبت برای شارژ، منفی برای برداشت")
    note: str | None = Field(default=None, max_length=500)


class CreditTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_id: int
    amount: int
    balance_after: int
    kind: str
    note: str | None
    created_at: datetime


# ---------- Commercial plans and subscription groups ----------
class ResourceAccessRequest(BaseModel):
    allowed_inbound_ids: list[int] | None = Field(default=None, max_length=1000)
    allowed_dns_tunnel_ids: list[int] | None = Field(default=None, max_length=1000)


class PlanBase(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    days: int = Field(default=30, ge=0, le=3650)
    data_limit_bytes: int | None = Field(default=None, ge=0)
    device_limit: int | None = Field(default=None, ge=1, le=100)
    price: int = Field(default=0, ge=0)
    is_active: bool = True


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    days: int | None = Field(default=None, ge=0, le=3650)
    data_limit_bytes: int | None = Field(default=None, ge=0)
    device_limit: int | None = Field(default=None, ge=1, le=100)
    price: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class PlanOut(PlanBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class SubscriptionGroupCreate(ResourceAccessRequest):
    name: str = Field(min_length=2, max_length=100)
    plan_id: int | None = None
    max_members: int = Field(default=1, ge=1, le=100)
    data_limit_bytes: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None
    is_active: bool = True
    note: str | None = Field(default=None, max_length=1000)


class SubscriptionGroupUpdate(ResourceAccessRequest):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    plan_id: int | None = None
    max_members: int | None = Field(default=None, ge=1, le=100)
    data_limit_bytes: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None
    is_active: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class SubscriptionMemberOut(BaseModel):
    id: int
    username: str
    status: str
    used_traffic_bytes: int


class SubscriptionGroupOut(ResourceAccessRequest):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token: str
    owner_admin_id: int | None
    plan_id: int | None
    max_members: int
    data_limit_bytes: int | None
    expire_at: datetime | None
    is_active: bool
    status: str
    used_traffic_bytes: int
    remaining_bytes: int | None
    note: str | None
    members: list[SubscriptionMemberOut] = []
    subscription_path: str | None = None
    created_at: datetime


class GroupMembersUpdate(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=200)


class RenewalRequest(BaseModel):
    plan_id: int
    reset_traffic: bool = True


class BulkUsersRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["enable", "disable", "reset_traffic", "delete"]


# ---------- Users ----------
class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr | None = None
    note: str | None = Field(default=None, max_length=1000)
    data_limit_bytes: int | None = Field(default=None, ge=0)
    device_limit: int | None = Field(default=None, ge=1, le=100)
    expire_at: datetime | None = None


class UserCreate(UserBase, ResourceAccessRequest):
    subscription_slug: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    is_active: bool = True
    plan_id: int | None = None
    subscription_id: int | None = None
    owner_admin_id: int | None = None


class UserUpdate(ResourceAccessRequest):
    subscription_slug: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    username: str | None = Field(default=None, min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr | None = None
    note: str | None = Field(default=None, max_length=1000)
    data_limit_bytes: int | None = Field(default=None, ge=0)
    device_limit: int | None = Field(default=None, ge=1, le=100)
    expire_at: datetime | None = None
    is_active: bool | None = None
    plan_id: int | None = None
    subscription_id: int | None = None


class UserOut(ResourceAccessRequest):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    uuid: str
    sub_token: str
    status: str
    is_active: bool
    data_limit_bytes: int | None
    used_traffic_bytes: int
    remaining_bytes: int | None
    upload_bytes: int
    download_bytes: int
    usage_percent: float
    device_limit: int | None
    expire_at: datetime | None
    last_online_at: datetime | None
    note: str | None
    plan_id: int | None = None
    subscription_id: int | None = None
    group_name: str | None = None
    created_at: datetime
    subscription_path: str
    group_subscription_path: str | None = None

    @classmethod
    def from_user(cls, user) -> "UserOut":
        group = user.subscription
        subscription_path = f"/sub/{user.sub_token}"
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            uuid=user.uuid,
            sub_token=user.sub_token,
            status=user.status,
            is_active=user.is_active,
            data_limit_bytes=user.data_limit_bytes,
            used_traffic_bytes=user.used_traffic_bytes,
            remaining_bytes=user.remaining_bytes,
            upload_bytes=user.upload_bytes,
            download_bytes=user.download_bytes,
            usage_percent=user.usage_percent,
            device_limit=user.device_limit,
            expire_at=user.expire_at,
            last_online_at=user.last_online_at,
            note=user.note,
            plan_id=user.plan_id,
            subscription_id=user.subscription_id,
            group_name=group.name if group else None,
            created_at=user.created_at,
            subscription_path=subscription_path,
            group_subscription_path=f"/sub/{group.token}" if group else None,
            allowed_inbound_ids=user.allowed_inbound_ids,
            allowed_dns_tunnel_ids=user.allowed_dns_tunnel_ids,
        )


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    size: int


class UsagePoint(BaseModel):
    date: str
    upload: int
    download: int


class UserUsageOut(BaseModel):
    user_id: int
    series: list[UsagePoint]
    by_inbound: list[dict]


# ---------- Nodes ----------
class NodeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=2, max_length=255)
    port: int = Field(default=443, ge=1, le=65535)
    api_address: str | None = Field(default=None, max_length=255)
    api_port: int | None = Field(default=None, ge=1, le=65535)
    note: str | None = Field(default=None, max_length=1000)
    traffic_coefficient: float = Field(default=1.0, ge=0.1, le=10)


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    address: str | None = Field(default=None, min_length=2, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    api_address: str | None = Field(default=None, max_length=255)
    api_port: int | None = Field(default=None, ge=1, le=65535)
    note: str | None = Field(default=None, max_length=1000)
    traffic_coefficient: float | None = Field(default=None, ge=0.1, le=10)


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    port: int
    api_address: str | None
    api_port: int | None
    api_key: str
    status: str
    is_local: bool
    is_online: bool
    traffic_coefficient: float
    cpu_usage: float
    memory_usage: float
    note: str | None
    last_seen_at: datetime | None
    created_at: datetime
    inbound_count: int = 0


# ---------- Inbounds ----------
class InboundBase(BaseModel):
    node_id: int | None = None
    tag: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    protocol: Literal["vless", "vmess", "trojan", "shadowsocks"] = "vless"
    listen: str = "0.0.0.0"
    port: int = Field(ge=1, le=65535)
    network: Literal["tcp", "ws", "grpc", "httpupgrade", "xhttp", "kcp"] = "tcp"
    security: Literal["reality", "tls", "none"] = "reality"
    remark: str = Field(min_length=2, max_length=120)
    sni: str | None = Field(default=None, max_length=255)
    host: str | None = Field(default=None, max_length=255)
    path: str | None = Field(default=None, max_length=255)
    service_name: str | None = Field(default=None, max_length=120)
    flow: str | None = Field(default=None, max_length=60)
    fingerprint: str | None = Field(default="chrome", max_length=40)
    alpn: str | None = Field(default=None, max_length=120)
    reality_public_key: str | None = Field(default=None, max_length=120)
    reality_private_key: str | None = Field(default=None, max_length=120)
    reality_short_id: str | None = Field(default=None, max_length=32)
    reality_dest: str | None = Field(default=None, max_length=255)
    tls_cert_path: str | None = Field(default=None, max_length=512)
    tls_key_path: str | None = Field(default=None, max_length=512)
    is_active: bool = True
    data_limit_bytes: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None
    reset_interval_days: int | None = Field(default=None, ge=1, le=365)
    extra_json: str | None = None

    @field_validator('extra_json')
    @classmethod
    def advanced_options(cls, value):
        from app.services.inbound_options import AdvancedInbound
        if value is not None:
            if len(value) > 65536:
                raise ValueError('Advanced inbound settings exceed 64 KiB.')
            return AdvancedInbound.model_validate_json(value).model_dump_json()
        return None


class InboundCreate(InboundBase):
    pass


class InboundUpdate(BaseModel):
    node_id: int | None = None
    tag: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    protocol: Literal["vless", "vmess", "trojan", "shadowsocks"] | None = None
    listen: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    network: Literal["tcp", "ws", "grpc", "httpupgrade", "xhttp", "kcp"] | None = None
    security: Literal["reality", "tls", "none"] | None = None
    remark: str | None = Field(default=None, min_length=2, max_length=120)
    sni: str | None = None
    host: str | None = None
    path: str | None = None
    service_name: str | None = None
    flow: str | None = None
    fingerprint: str | None = None
    alpn: str | None = None
    reality_public_key: str | None = None
    reality_private_key: str | None = None
    reality_short_id: str | None = None
    reality_dest: str | None = None
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    is_active: bool | None = None
    data_limit_bytes: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None
    reset_interval_days: int | None = Field(default=None, ge=1, le=365)
    extra_json: str | None = None

    _advanced_options = field_validator('extra_json')(InboundBase.advanced_options.__func__)


class InboundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_id: int | None
    node_name: str | None = None
    tag: str
    protocol: str
    listen: str
    port: int
    network: str
    security: str
    remark: str
    sni: str | None
    host: str | None
    path: str | None
    service_name: str | None
    flow: str | None
    fingerprint: str | None
    alpn: str | None
    reality_public_key: str | None
    reality_private_key: str | None
    reality_short_id: str | None
    reality_dest: str | None
    tls_cert_path: str | None
    tls_key_path: str | None
    is_active: bool
    total_bytes: int
    data_limit_bytes: int | None = None
    expire_at: datetime | None = None
    reset_interval_days: int | None = None
    last_reset_at: datetime | None = None
    usage_percent: float = 0.0
    status: str = "active"
    extra_json: str | None = None
    created_at: datetime


class KeyPairOut(BaseModel):
    private_key: str
    public_key: str
    short_id: str


class InboundBulkStatus(BaseModel):
    inbound_ids: list[int] = Field(min_length=1, max_length=500)
    is_active: bool


class InboundBulkReset(BaseModel):
    inbound_ids: list[int] = Field(min_length=1, max_length=500)


class InboundBulkDelete(BaseModel):
    inbound_ids: list[int] = Field(min_length=1, max_length=500)


# ---------- DNS tunnels / DNSTT / NoizDNS ----------
class DnsTunnelBase(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    domain: str = Field(min_length=4, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$")
    upstream_port: int = Field(default=5310, ge=1, le=65535)
    target_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    target_port: int = Field(default=1080, ge=1, le=65535)
    mtu: int = Field(default=1232, ge=512, le=1400)
    resolver: str = Field(default="8.8.8.8:53:0", max_length=255)
    noizdns_enabled: bool = True
    is_active: bool = True
    managed_gateway: bool = False
    note: str | None = Field(default=None, max_length=1000)


class DnsTunnelCreate(DnsTunnelBase):
    private_key: str | None = Field(default=None, max_length=128)
    public_key: str | None = Field(default=None, max_length=128)


class DnsTunnelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    domain: str | None = Field(
        default=None,
        min_length=4,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$",
    )
    upstream_port: int | None = Field(default=None, ge=1, le=65535)
    target_host: str | None = Field(default=None, min_length=1, max_length=255)
    target_port: int | None = Field(default=None, ge=1, le=65535)
    mtu: int | None = Field(default=None, ge=512, le=1400)
    resolver: str | None = Field(default=None, max_length=255)
    noizdns_enabled: bool | None = None
    is_active: bool | None = None
    managed_gateway: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class DnsTunnelOut(DnsTunnelBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    private_key: str
    public_key: str
    created_at: datetime


class DnsKeyPairOut(BaseModel):
    private_key: str
    public_key: str


class DnsTunnelSetupOut(BaseModel):
    id: int
    name: str
    domain: str
    key_path: str
    command: str
    systemd_unit: str
    dns_records: list[str]
    multiplexer_entry: dict
    client_uri_template_dnstt: str
    client_uri_template_noizdns: str | None
    notes: list[str]


class DnsMultiplexerOut(BaseModel):
    listen: str
    routes: list[dict]
    config: dict
    command: str


# ---------- Subscriptions ----------
class SubscriptionInfo(BaseModel):
    username: str
    status: str
    expire_at: datetime | None
    data_limit_bytes: int | None
    used_traffic_bytes: int
    upload_bytes: int
    download_bytes: int
    links: list[dict]
    dns_links: list[dict] = []
    subscription_url: str
    clash_url: str
    page_url: str = ""
    format_urls: dict[str, str] = Field(default_factory=dict)
    subscription_type: str = "single"
    group_name: str | None = None
    max_members: int = 1
    members: list[dict] = []
    panel_title: str = "SpecterGate"
    panel_description: str = ""
    support_url: str = ""
    announcement: str = ""


class SubscriptionLink(BaseModel):
    remark: str
    protocol: str
    uri: str


# ---------- Dashboard / settings / system ----------
class DashboardOverview(BaseModel):
    total_users: int
    active_users: int
    expired_users: int
    limited_users: int
    disabled_users: int
    total_nodes: int
    online_nodes: int
    total_inbounds: int
    active_inbounds: int
    upload_bytes: int
    download_bytes: int
    total_traffic_bytes: int
    today_traffic_bytes: int
    traffic_series: list[dict]
    protocol_series: list[dict]
    recent_users: list[UserOut]
    nodes: list[NodeOut]


class SettingsOut(BaseModel):
    time_zone: str = 'Asia/Tehran'
    calendar: Literal['persian', 'gregory'] = 'persian'
    panel_title: str
    panel_description: str
    subscription_base_url: str
    public_host: str
    default_expiry_days: int
    default_data_limit_gb: int
    subscription_path_prefix: str
    support_url: str
    announcement: str
    registration_enabled: bool


class SettingsUpdate(BaseModel):
    time_zone: str | None = Field(default=None, max_length=80)
    calendar: Literal['persian', 'gregory'] | None = None

    @field_validator('time_zone')
    @classmethod
    def timezone_name(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise ValueError('Use a valid IANA time zone, e.g. Asia/Tehran.') from None
        return value
    panel_title: str | None = Field(default=None, max_length=100)
    panel_description: str | None = Field(default=None, max_length=300)
    subscription_base_url: str | None = Field(default=None, max_length=300)
    public_host: str | None = Field(default=None, max_length=255)
    default_expiry_days: int | None = Field(default=None, ge=0, le=3650)
    default_data_limit_gb: int | None = Field(default=None, ge=0)
    subscription_path_prefix: str | None = Field(default=None, max_length=60)
    support_url: str | None = Field(default=None, max_length=300)
    announcement: str | None = Field(default=None, max_length=1000)
    registration_enabled: bool | None = None


class XrayStatusOut(BaseModel):
    enabled: bool
    binary_available: bool
    running: bool
    config_path: str
    config_exists: bool
    message: str
    pid: int | None = None


class XrayApplyOut(BaseModel):
    ok: bool
    message: str
    config_path: str
    inbound_count: int
    client_count: int
    validation_output: str = ""


class OperationResult(BaseModel):
    ok: bool
    message: str


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_username: str
    action: str
    target_type: str
    target_id: str | None
    detail: str | None
    ip_address: str | None
    created_at: datetime


class TwoFactorSetupOut(BaseModel):
    secret: str
    uri: str
    qr_svg: str
    recovery_codes: list[str]


class TwoFactorEnableRequest(BaseModel):
    secret: str = Field(min_length=32, max_length=32, pattern=r"^[A-Z2-7]+$")
    code: str = Field(pattern=r"^[0-9]{6}$")
    recovery_codes: list[str] = Field(min_length=8, max_length=8)


class TwoFactorDisableRequest(BaseModel):
    password: str
