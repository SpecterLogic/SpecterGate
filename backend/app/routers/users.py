from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission, get_current_admin
from app.models import Admin, Plan, SubscriptionGroup, TrafficSample, VPNUser, new_uuid
from app.schemas import (
    OperationResult,
    UsagePoint,
    UserCreate,
    UserOut,
    UserPage,
    UserUpdate,
    UserUsageOut,
    RenewalRequest,
    BulkUsersRequest,
)
from app.services.audit import write_audit
from app.services.permissions import (
    can_assign_owner,
    charge_plan,
    enforce_user_quota,
    ensure_user_access,
    resolve_plan,
    user_query_for,
    visible_admin_ids,
)
from app.services.settings import get_setting
from app.services.resource_access import apply_resource_access, admin_inbound_allowed


router = APIRouter(prefix="/users", tags=["users"])
read_access = require_permission("users.read")
write_access = require_permission("users.write")
delete_access = require_permission("users.delete")


@router.get("/access-options")
def access_options(db: Session = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    from app.services.permissions import has_permission
    if not any(has_permission(admin, p) for p in ("users.read", "subscriptions.read")):
        raise HTTPException(status_code=403, detail="مجوز مشاهده منابع را ندارید.")
    from app.models import Inbound, DnsTunnel
    return {
        "inbounds": [{"id": item.id, "name": item.remark, "tag": item.tag, "protocol": item.protocol, "is_active": item.is_active} for item in db.query(Inbound).order_by(Inbound.id).all() if admin_inbound_allowed(admin, item.id)],
        "dns_tunnels": [{"id": item.id, "name": item.name, "domain": item.domain, "is_active": item.is_active} for item in db.query(DnsTunnel).order_by(DnsTunnel.id).all()],
    }


@router.post("/bulk", response_model=OperationResult)
def bulk_users(payload: BulkUsersRequest, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(write_access)):
    from app.services.permissions import require
    if payload.action == "delete":
        require(admin, "users.delete")
    users = db.query(VPNUser).filter(VPNUser.id.in_(payload.user_ids)).all()
    if len(users) != len(set(payload.user_ids)):
        raise HTTPException(status_code=404, detail="یکی از کاربران پیدا نشد.")
    for user in users:
        ensure_user_access(db, admin, user)
    for user in users:
        if payload.action == "delete":
            db.delete(user)
        elif payload.action == "reset_traffic":
            user.upload_bytes = user.download_bytes = 0
        else:
            user.is_active = payload.action == "enable"
    db.commit()
    write_audit(db, admin, "bulk_users", "users", None, f"{payload.action}: {len(users)}", get_client_ip(request))
    return OperationResult(ok=True, message=f"عملیات روی {len(users)} کاربر انجام شد.")


@router.post("/{user_id}/renew", response_model=UserOut)
def renew_user(user_id: int, payload: RenewalRequest, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(write_access)):
    from app.models import as_utc, utcnow
    user = db.get(VPNUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    plan = resolve_plan(db, admin, payload.plan_id)
    charge_plan(db, admin, plan)
    now = utcnow()
    start = max(as_utc(user.expire_at) or now, now)
    user.expire_at = start + timedelta(days=plan.days) if plan.days else None
    user.data_limit_bytes = plan.data_limit_bytes
    user.device_limit = plan.device_limit
    user.plan_id = plan.id
    user.is_active = True
    if payload.reset_traffic:
        user.upload_bytes = user.download_bytes = 0
    db.commit()
    db.refresh(user)
    write_audit(db, admin, "renew_user", "user", user.id, f"تمدید با پلن {plan.name}", get_client_ip(request))
    return UserOut.from_user(user)


def _used_bytes():
    return func.coalesce(VPNUser.upload_bytes, 0) + func.coalesce(VPNUser.download_bytes, 0)


def _apply_status_filter(query, status: str, now: datetime):
    used = _used_bytes()
    not_expired = or_(VPNUser.expire_at.is_(None), VPNUser.expire_at > now)
    if status == "disabled":
        return query.filter(VPNUser.is_active.is_(False))
    if status == "expired":
        return query.filter(VPNUser.is_active.is_(True), VPNUser.expire_at <= now)
    if status == "limited":
        return query.filter(
            VPNUser.is_active.is_(True),
            not_expired,
            VPNUser.data_limit_bytes.is_not(None),
            used >= VPNUser.data_limit_bytes,
        )
    if status == "active":
        return query.filter(
            VPNUser.is_active.is_(True),
            not_expired,
            or_(VPNUser.data_limit_bytes.is_(None), used < VPNUser.data_limit_bytes),
        )
    return query


def _group_for_user(db: Session, admin: Admin, group_id: int | None, current_user_id: int | None = None) -> SubscriptionGroup | None:
    if group_id is None:
        return None
    group = db.get(SubscriptionGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="اشتراک گروهی پیدا نشد.")
    ids = visible_admin_ids(db, admin)
    if ids is not None and group.owner_admin_id not in ids:
        raise HTTPException(status_code=403, detail="این اشتراک در محدودهٔ دسترسی شما نیست.")
    if group.max_members and current_user_id is None and len(group.members) >= group.max_members:
        raise HTTPException(status_code=400, detail="ظرفیت اعضای این اشتراک تکمیل شده است.")
    return group


@router.get("", response_model=UserPage)
def list_users(
    search: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status"),
    subscription_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: Admin = Depends(read_access),
):
    now = datetime.now(timezone.utc)
    query = user_query_for(db, admin)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                VPNUser.username.ilike(term),
                VPNUser.email.ilike(term),
                VPNUser.note.ilike(term),
            )
        )
    if status_filter:
        # Effective status includes shared quotas and administrator restrictions.
        ids = [user.id for user in query.all() if user.status == status_filter]
        query = query.filter(VPNUser.id.in_(ids))
    if subscription_id is not None:
        query = query.filter(VPNUser.subscription_id == subscription_id)
    total = query.count()
    users = query.order_by(VPNUser.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return UserPage(
        items=[UserOut.from_user(user) for user in users],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    if db.query(VPNUser).filter(VPNUser.username == payload.username).first():
        raise HTTPException(status_code=409, detail="این نام کاربری قبلاً ثبت شده است.")

    enforce_user_quota(db, admin)
    target_admin_id = can_assign_owner(db, admin, payload.owner_admin_id)
    target_admin = db.get(Admin, target_admin_id) or admin
    resolve_plan(db, target_admin, payload.plan_id)
    if target_admin.id != admin.id:
        enforce_user_quota(db, target_admin)

    plan: Plan | None = resolve_plan(db, admin, payload.plan_id)
    group = _group_for_user(db, admin, payload.subscription_id)

    data = payload.model_dump()
    data.pop("owner_admin_id", None)
    access_data = {key: data.pop(key) for key in ("allowed_inbound_ids", "allowed_dns_tunnel_ids")}
    if plan:
        if "data_limit_bytes" not in payload.model_fields_set:
            data["data_limit_bytes"] = plan.data_limit_bytes
        if "device_limit" not in payload.model_fields_set:
            data["device_limit"] = plan.device_limit
        if "expire_at" not in payload.model_fields_set and plan.days > 0:
            data["expire_at"] = datetime.now(timezone.utc) + timedelta(days=plan.days)
    if "expire_at" not in payload.model_fields_set and not plan:
        default_days = int(get_setting(db, "default_expiry_days", 0) or 0)
        if default_days > 0:
            data["expire_at"] = datetime.now(timezone.utc) + timedelta(days=default_days)
    if "data_limit_bytes" not in payload.model_fields_set and not plan:
        default_gb = int(get_setting(db, "default_data_limit_gb", 0) or 0)
        if default_gb > 0:
            data["data_limit_bytes"] = default_gb * 1024**3
    if group:
        data["subscription_id"] = group.id
    if plan and (admin.require_template or target_admin.require_template):
        data["data_limit_bytes"] = plan.data_limit_bytes
        data["device_limit"] = plan.device_limit
        data["expire_at"] = datetime.now(timezone.utc) + timedelta(days=plan.days) if plan.days else None

    charge_plan(db, admin, plan)
    user = VPNUser(
        **data,
        uuid=new_uuid(),
        password=secrets.token_urlsafe(16),
        sub_token=secrets.token_urlsafe(24),
        created_by=target_admin_id,
    )
    apply_resource_access(db, user, access_data, admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit(
        db,
        admin,
        "create_user",
        "user",
        user.id,
        f"ایجاد کاربر {user.username}" + (f" با پلن {plan.name}" if plan else ""),
        get_client_ip(request),
    )
    return UserOut.from_user(user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(read_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    return UserOut.from_user(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    data = payload.model_dump(exclude_unset=True)
    apply_resource_access(db, user, data, admin)
    if admin.require_template and any(key in data for key in ("data_limit_bytes", "device_limit", "expire_at", "plan_id")):
        raise HTTPException(status_code=403, detail="تغییر مشخصات پلن فقط با عملیات تمدید مجاز است.")
    if "username" in data and data["username"] != user.username:
        if db.query(VPNUser).filter(VPNUser.username == data["username"]).first():
            raise HTTPException(status_code=409, detail="این نام کاربری قبلاً ثبت شده است.")
    if "plan_id" in data and data["plan_id"] is not None:
        resolve_plan(db, admin, data["plan_id"])
    if "subscription_id" in data:
        group = _group_for_user(db, admin, data["subscription_id"], current_user_id=user.id)
        if group and user.subscription_id != group.id:
            if len([member for member in group.members if member.id != user.id]) >= group.max_members:
                raise HTTPException(status_code=400, detail="ظرفیت اعضای این اشتراک تکمیل شده است.")
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    write_audit(
        db,
        admin,
        "update_user",
        "user",
        user.id,
        f"ویرایش کاربر {user.username}",
        get_client_ip(request),
    )
    return UserOut.from_user(user)


@router.delete("/{user_id}", response_model=OperationResult)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(delete_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    username = user.username
    db.delete(user)
    db.commit()
    write_audit(
        db,
        admin,
        "delete_user",
        "user",
        user_id,
        f"حذف کاربر {username}",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="کاربر حذف شد.")


@router.post("/{user_id}/reset-traffic", response_model=UserOut)
def reset_traffic(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    user.upload_bytes = 0
    user.download_bytes = 0
    db.query(TrafficSample).filter(TrafficSample.user_id == user.id).delete()
    db.commit()
    db.refresh(user)
    write_audit(db, admin, "reset_traffic", "user", user.id, f"ریست مصرف {user.username}", get_client_ip(request))
    return UserOut.from_user(user)


@router.post("/{user_id}/revoke-subscription", response_model=UserOut)
def revoke_subscription(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    user.sub_token = secrets.token_urlsafe(24)
    db.commit()
    db.refresh(user)
    write_audit(
        db,
        admin,
        "revoke_subscription",
        "user",
        user.id,
        f"ابطال لینک اشتراک {user.username}",
        get_client_ip(request),
    )
    return UserOut.from_user(user)


@router.post("/{user_id}/rotate-uuid", response_model=UserOut)
def rotate_uuid(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    user.uuid = new_uuid()
    user.password = secrets.token_urlsafe(16)
    db.commit()
    db.refresh(user)
    write_audit(db, admin, "rotate_uuid", "user", user.id, f"چرخش UUID {user.username}", get_client_ip(request))
    return UserOut.from_user(user)


@router.get("/{user_id}/usage", response_model=UserUsageOut)
def user_usage(
    user_id: int,
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    admin: Admin = Depends(read_access),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    samples = (
        db.query(TrafficSample)
        .filter(TrafficSample.user_id == user_id, TrafficSample.recorded_at >= start)
        .order_by(TrafficSample.recorded_at.asc())
        .all()
    )
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"upload": 0, "download": 0})
    for sample in samples:
        key = sample.recorded_at.date().isoformat()
        buckets[key]["upload"] += sample.upload_bytes
        buckets[key]["download"] += sample.download_bytes
    series = [
        UsagePoint(date=key, upload=value["upload"], download=value["download"])
        for key, value in sorted(buckets.items())
    ]
    return UserUsageOut(user_id=user_id, series=series, by_inbound=[])
