from __future__ import annotations

import enum
import secrets
import uuid as uuid_lib
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_token() -> str:
    return secrets.token_urlsafe(24)


def new_uuid() -> str:
    return str(uuid_lib.uuid4())


class SslCertificate(Base):
    __tablename__ = "ssl_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    issuer: Mapped[str] = mapped_column(String(100), default="Let's Encrypt")
    cert_path: Mapped[str] = mapped_column(String(500))
    key_path: Mapped[str] = mapped_column(String(500))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WireGuardPeer(Base):
    __tablename__ = "wireguard_peers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"), unique=True)
    public_key: Mapped[str] = mapped_column(String(44), unique=True)
    address: Mapped[str] = mapped_column(String(45), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_rx: Mapped[int] = mapped_column(BigInteger, default=0)
    last_tx: Mapped[int] = mapped_column(BigInteger, default=0)
    counter_epoch: Mapped[str] = mapped_column(String(80), default="")


class AmneziaPeer(Base):
    __tablename__ = "amnezia_peers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"), unique=True)
    public_key: Mapped[str] = mapped_column(String(44), unique=True)
    address: Mapped[str] = mapped_column(String(45), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_rx: Mapped[int] = mapped_column(BigInteger, default=0)
    last_tx: Mapped[int] = mapped_column(BigInteger, default=0)
    counter_epoch: Mapped[str] = mapped_column(String(80), default="")


class AdminRole(str, enum.Enum):
    superadmin = "superadmin"
    admin = "admin"
    reseller = "reseller"
    support = "support"
    viewer = "viewer"


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, native_enum=False), default=AdminRole.admin
    )
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    scope: Mapped[str] = mapped_column(String(20), default="all")  # all | own | none
    max_users: Mapped[int | None] = mapped_column(Integer)
    traffic_quota_bytes: Mapped[int | None] = mapped_column(BigInteger)
    credit: Mapped[int] = mapped_column(BigInteger, default=0)
    require_template: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions_json: Mapped[str | None] = mapped_column(Text)
    allowed_inbound_ids_json: Mapped[str | None] = mapped_column(Text)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_codes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    parent: Mapped[Admin | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Admin]] = relationship(back_populates="parent")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    days: Mapped[int] = mapped_column(Integer, default=30)
    data_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    device_limit: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SubscriptionGroup(Base):
    __tablename__ = "subscription_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True, default=new_token)
    owner_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), index=True
    )
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"))
    max_members: Mapped[int] = mapped_column(Integer, default=1)
    data_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    members: Mapped[list[VPNUser]] = relationship(back_populates="subscription")
    owner: Mapped[Admin | None] = relationship(foreign_keys=[owner_admin_id])
    access_policy: Mapped[GroupResourceAccess | None] = relationship(cascade="all, delete-orphan", uselist=False)

    @property
    def allowed_inbound_ids(self) -> list[int] | None:
        return self.access_policy.inbound_ids if self.access_policy else None

    @property
    def allowed_dns_tunnel_ids(self) -> list[int] | None:
        return self.access_policy.tunnel_ids if self.access_policy else None

    @property
    def used_traffic_bytes(self) -> int:
        return sum(member.used_traffic_bytes for member in self.members)

    @property
    def remaining_bytes(self) -> int | None:
        if self.data_limit_bytes is None:
            return None
        return max(0, int(self.data_limit_bytes) - self.used_traffic_bytes)

    @property
    def status(self) -> str:
        if not self.is_active:
            return "disabled"
        now = utcnow()
        if self.expire_at is not None and (as_utc(self.expire_at) or now) <= now:
            return "expired"
        if self.data_limit_bytes is not None and self.used_traffic_bytes >= self.data_limit_bytes:
            return "limited"
        if any(member.status in {"disabled", "expired", "limited"} for member in self.members):
            # The group stays usable as long as at least one member is active.
            if not any(member.status == "active" for member in self.members):
                return "disabled"
        return "active"


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger, default=0)
    kind: Mapped[str] = mapped_column(String(40), default="adjustment")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=443)
    api_address: Mapped[str | None] = mapped_column(String(255))
    api_port: Mapped[int | None] = mapped_column(Integer)
    api_key: Mapped[str] = mapped_column(String(96), unique=True, default=new_token)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    traffic_coefficient: Mapped[float] = mapped_column(default=1.0)
    cpu_usage: Mapped[float] = mapped_column(default=0.0)
    memory_usage: Mapped[float] = mapped_column(default=0.0)
    note: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    inbounds: Mapped[list[Inbound]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )

    @property
    def is_online(self) -> bool:
        if self.is_local:
            return self.status in {"online", "unknown"}
        if self.status != "online" or not self.last_seen_at:
            return False
        last_seen = as_utc(self.last_seen_at)
        return (utcnow() - last_seen).total_seconds() < 180


class VPNUser(Base):
    __tablename__ = "vpn_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    uuid: Mapped[str] = mapped_column(String(64), unique=True, default=new_uuid, index=True)
    password: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_urlsafe(16))
    sub_token: Mapped[str] = mapped_column(String(96), unique=True, default=new_token, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    data_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    upload_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    download_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    device_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_notified_status: Mapped[str | None] = mapped_column(String(20))
    hwid_limit: Mapped[int | None] = mapped_column(Integer)
    traffic_reset_days: Mapped[int | None] = mapped_column(Integer)
    traffic_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewal_days: Mapped[int | None] = mapped_column(Integer)
    renewal_remaining: Mapped[int] = mapped_column(Integer, default=0)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscription_groups.id", ondelete="SET NULL"), index=True
    )
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    samples: Mapped[list[TrafficSample]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscription: Mapped[SubscriptionGroup | None] = relationship(back_populates="members")
    creator: Mapped[Admin | None] = relationship(foreign_keys=[created_by])
    access_policy: Mapped[UserResourceAccess | None] = relationship(cascade="all, delete-orphan", uselist=False)

    @property
    def allowed_inbound_ids(self) -> list[int] | None:
        return self.access_policy.inbound_ids if self.access_policy else None

    @property
    def allowed_dns_tunnel_ids(self) -> list[int] | None:
        return self.access_policy.tunnel_ids if self.access_policy else None

    @property
    def used_traffic_bytes(self) -> int:
        return int(self.upload_bytes or 0) + int(self.download_bytes or 0)

    @property
    def remaining_bytes(self) -> int | None:
        if self.data_limit_bytes is None:
            return None
        return max(0, int(self.data_limit_bytes) - self.used_traffic_bytes)

    @property
    def status(self) -> str:
        if not self.is_active:
            return "disabled"
        from sqlalchemy.orm import object_session
        from app.services.permissions import account_status
        session = object_session(self)
        if session is not None and self.creator is not None:
            owner_status = account_status(session, self.creator)
            if owner_status != "active":
                return owner_status
        now = utcnow()
        group = self.subscription
        if group is not None:
            if not group.is_active:
                return "disabled"
            if group.expire_at is not None and (as_utc(group.expire_at) or now) <= now:
                return "expired"
            if group.data_limit_bytes is not None and group.used_traffic_bytes >= group.data_limit_bytes:
                return "limited"
        if self.expire_at is not None and (as_utc(self.expire_at) or now) <= now:
            return "expired"
        if self.data_limit_bytes is not None and self.used_traffic_bytes >= self.data_limit_bytes:
            return "limited"
        return "active"

    @property
    def usage_percent(self) -> float:
        if not self.data_limit_bytes:
            return 0.0
        return min(100.0, round(self.used_traffic_bytes / self.data_limit_bytes * 100, 1))


class Inbound(Base):
    __tablename__ = "inbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engine: Mapped[str] = mapped_column(String(16), default="xray")
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), index=True
    )
    tag: Mapped[str] = mapped_column(String(64), unique=True)
    protocol: Mapped[str] = mapped_column(String(20), default="vless")
    listen: Mapped[str] = mapped_column(String(80), default="0.0.0.0")
    port: Mapped[int] = mapped_column(Integer)
    network: Mapped[str] = mapped_column(String(20), default="tcp")
    security: Mapped[str] = mapped_column(String(20), default="reality")
    remark: Mapped[str] = mapped_column(String(120))

    sni: Mapped[str | None] = mapped_column(String(255))
    host: Mapped[str | None] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(String(255))
    service_name: Mapped[str | None] = mapped_column(String(120))
    flow: Mapped[str | None] = mapped_column(String(60))
    fingerprint: Mapped[str | None] = mapped_column(String(40))
    alpn: Mapped[str | None] = mapped_column(String(120))

    reality_public_key: Mapped[str | None] = mapped_column(String(120))
    reality_private_key: Mapped[str | None] = mapped_column(String(120))
    reality_short_id: Mapped[str | None] = mapped_column(String(32))
    reality_dest: Mapped[str | None] = mapped_column(String(255))

    tls_cert_path: Mapped[str | None] = mapped_column(String(512))
    tls_key_path: Mapped[str | None] = mapped_column(String(512))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    data_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    download_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    extra_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    node: Mapped[Node | None] = relationship(back_populates="inbounds")

    @property
    def total_bytes(self) -> int:
        return int(self.upload_bytes or 0) + int(self.download_bytes or 0)

    @property
    def status(self) -> str:
        if not self.is_active:
            return "disabled"
        now = utcnow()
        if self.expire_at is not None and (as_utc(self.expire_at) or now) <= now:
            return "expired"
        if self.data_limit_bytes is not None and self.total_bytes >= self.data_limit_bytes:
            return "limited"
        return "active"

    @property
    def usage_percent(self) -> float:
        if not self.data_limit_bytes or self.data_limit_bytes <= 0:
            return 0.0
        return min(100.0, round(self.total_bytes / self.data_limit_bytes * 100, 1))

    @property
    def is_usable(self) -> bool:
        return self.status == "active"


class DnsTunnel(Base):
    """A DNSTT server profile. NoizDNS shares the server and changes client behavior."""

    __tablename__ = "dns_tunnels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    upstream_port: Mapped[int] = mapped_column(Integer, default=5310)
    target_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1")
    target_port: Mapped[int] = mapped_column(Integer, default=1080)
    mtu: Mapped[int] = mapped_column(Integer, default=1232)
    resolver: Mapped[str] = mapped_column(String(255), default="8.8.8.8:53:0")
    private_key: Mapped[str] = mapped_column(String(128))
    public_key: Mapped[str] = mapped_column(String(128))
    noizdns_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    gateway_config: Mapped[TunnelGatewaySettings | None] = relationship(cascade="all, delete-orphan", uselist=False)

    @property
    def managed_gateway(self) -> bool:
        return bool(self.gateway_config and self.gateway_config.enabled)


class TunnelGatewaySettings(Base):
    __tablename__ = "tunnel_gateway_settings"
    tunnel_id: Mapped[int] = mapped_column(ForeignKey("dns_tunnels.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class UserResourceAccess(Base):
    __tablename__ = "user_resource_access"
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"), primary_key=True)
    inbound_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tunnel_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


class GroupResourceAccess(Base):
    __tablename__ = "group_resource_access"
    group_id: Mapped[int] = mapped_column(ForeignKey("subscription_groups.id", ondelete="CASCADE"), primary_key=True)
    inbound_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tunnel_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


class TrafficSample(Base):
    __tablename__ = "traffic_samples"
    __table_args__ = (Index("ix_traffic_recorded_at", "recorded_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"))
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="SET NULL"))
    inbound_id: Mapped[int | None] = mapped_column(ForeignKey("inbounds.id", ondelete="SET NULL"))
    upload_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    download_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[VPNUser] = relationship(back_populates="samples")


class NodeUsageReceipt(Base):
    __tablename__ = "node_usage_receipts"
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProtectedSetting(Base):
    __tablename__ = "protected_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TelegramAdminBinding(Base):
    __tablename__ = "telegram_admin_bindings"
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    allow_create: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramCommandReceipt(Base):
    __tablename__ = "telegram_command_receipts"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    username: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    admin_username: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_user_device"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(100), default="Client")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(180), unique=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
