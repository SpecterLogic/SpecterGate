from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Admin,
    AdminRole,
    DnsTunnel,
    Inbound,
    Node,
    Plan,
    SubscriptionGroup,
    TrafficSample,
    VPNUser,
    new_uuid,
    new_token,
)
from app.security import hash_password
from app.services.dns import generate_keypair as generate_dns_keypair
from app.services.settings import ensure_default_settings
from app.services.xray import generate_keypair


def _demo_users(db: Session, admin: Admin) -> None:
    random.seed(2026)
    now = datetime.now(timezone.utc)
    names = [
        "sara_ahmadi",
        "mehdi_dev",
        "negar_m",
        "amir_h",
        "parisa_k",
        "reza_net",
        "shirin",
        "hossein_vpn",
    ]
    plans = [
        (50, 30, "پلن ماهانه ۵۰ گیگ"),
        (100, 60, "پلن دو ماهه ۱۰۰ گیگ"),
        (30, 7, "پلن هفتگی"),
        (None, 90, "نامحدود سه ماهه"),
        (20, 3, "تست رایگان"),
    ]
    for index, name in enumerate(names):
        limit_gb, days, note = plans[index % len(plans)]
        user = VPNUser(
            username=name,
            email=f"{name}@example.com",
            uuid=new_uuid(),
            password=secrets.token_urlsafe(16),
            sub_token=secrets.token_urlsafe(24),
            is_active=index != 6,
            data_limit_bytes=limit_gb * 1024**3 if limit_gb else None,
            device_limit=2 if index % 3 else None,
            expire_at=now + timedelta(days=days if index != 7 else -2),
            note=note,
            created_by=admin.id,
            created_at=now - timedelta(days=45 - index * 4),
        )
        user.upload_bytes = random.randint(1, 15) * 1024**3
        user.download_bytes = random.randint(4, 45) * 1024**3
        db.add(user)
        db.flush()
        for day in range(7, 0, -1):
            sample_time = now - timedelta(days=day, hours=random.randint(0, 12))
            db.add(
                TrafficSample(
                    user_id=user.id,
                    upload_bytes=random.randint(20, 400) * 1024**2,
                    download_bytes=random.randint(80, 1800) * 1024**2,
                    recorded_at=sample_time,
                )
            )
    db.commit()


def _demo_inbounds(db: Session, node: Node) -> None:
    if db.query(Inbound).count() > 0:
        return
    keys = generate_keypair()
    db.add(
        Inbound(
            node_id=node.id,
            tag="vless-reality",
            protocol="vless",
            listen="0.0.0.0",
            port=8443,
            network="tcp",
            security="reality",
            remark="Reality · Direct",
            sni="www.cloudflare.com",
            flow="xtls-rprx-vision",
            fingerprint="chrome",
            reality_public_key=keys["public_key"],
            reality_private_key=keys["private_key"],
            reality_short_id=keys["short_id"],
            reality_dest="www.cloudflare.com:443",
            is_active=True,
        )
    )
    db.add(
        Inbound(
            node_id=node.id,
            tag="vmess-ws",
            protocol="vmess",
            listen="0.0.0.0",
            port=2087,
            network="ws",
            security="none",
            remark="VMess · WebSocket",
            host="cdn.example.com",
            path="/spectergate",
            is_active=True,
        )
    )
    db.commit()


def _demo_commercial(db: Session) -> None:
    if db.query(Plan).count() == 0:
        db.add_all(
            [
                Plan(name="پلن ماهانه ۵۰ گیگ", days=30, data_limit_bytes=50 * 1024**3, device_limit=2, price=120_000),
                Plan(name="پلن دو ماهه ۱۰۰ گیگ", days=60, data_limit_bytes=100 * 1024**3, device_limit=3, price=210_000),
                Plan(name="پلن نامحدود", days=30, data_limit_bytes=None, device_limit=2, price=350_000),
            ]
        )
        db.commit()

    if db.query(SubscriptionGroup).count() == 0:
        users = db.query(VPNUser).filter(VPNUser.is_active.is_(True)).limit(2).all()
        admin = db.query(Admin).filter(Admin.is_owner.is_(True)).first()
        plan = db.query(Plan).filter(Plan.price == 120_000).first()
        now = datetime.now(timezone.utc)
        group = SubscriptionGroup(
            name="اشتراک خانوادگی نمونه",
            token=new_token(),
            owner_admin_id=admin.id if admin else None,
            plan_id=plan.id if plan else None,
            max_members=3,
            data_limit_bytes=150 * 1024**3,
            expire_at=now + timedelta(days=45),
            is_active=True,
            note="یک لینک اشتراک برای چند کاربر",
        )
        db.add(group)
        db.flush()
        for user in users:
            user.subscription_id = group.id
        db.commit()


def seed_database(db: Session) -> None:
    ensure_default_settings(db)

    admin = db.query(Admin).filter(Admin.username == settings.admin_username).first()
    if admin is None:
        admin = Admin(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role=AdminRole.superadmin,
            is_owner=True,
            scope="all",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    elif admin.username == settings.admin_username and not admin.is_owner:
        admin.is_owner = True
        admin.scope = "all"
        db.commit()

    local_node = db.query(Node).filter(Node.is_local.is_(True)).first()
    if local_node is None:
        local_node = Node(
            name="Local",
            address=settings.public_host,
            port=443,
            api_address="127.0.0.1",
            api_port=10085,
            api_key=secrets.token_urlsafe(32),
            status="online",
            is_local=True,
            note="هستهٔ Xray روی همین سرور",
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(local_node)
        db.commit()
        db.refresh(local_node)

    if settings.demo_data and db.query(VPNUser).count() == 0:
        _demo_users(db, admin)
    if settings.demo_data:
        _demo_inbounds(db, local_node)
        _demo_commercial(db)
        if db.query(DnsTunnel).count() == 0:
            keys = generate_dns_keypair()
            db.add(
                DnsTunnel(
                    name="DNSTT Demo",
                    domain="t.example.com",
                    upstream_port=5310,
                    target_host="127.0.0.1",
                    target_port=1081,
                    mtu=1232,
                    resolver="8.8.8.8:53:0",
                    private_key=keys["private_key"],
                    public_key=keys["public_key"],
                    noizdns_enabled=True,
                    is_active=True,
                    note="پروفایل نمونه برای DNS fallback",
                )
            )
            db.commit()
