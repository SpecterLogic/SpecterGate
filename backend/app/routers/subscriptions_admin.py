from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin, Plan, SubscriptionGroup, VPNUser
from app.schemas import (
    GroupMembersUpdate,
    OperationResult,
    SubscriptionGroupCreate,
    SubscriptionGroupOut,
    SubscriptionGroupUpdate,
    UserOut,
)
from app.services.audit import write_audit
from app.services.groups import build_group_out
from app.services.resource_access import apply_resource_access
from app.services.permissions import (
    charge_plan,
    ensure_user_access,
    resolve_plan,
    visible_admin_ids,
)


router = APIRouter(prefix="/subscriptions", tags=["subscriptions-admin"])


def _scope_groups(db: Session, admin: Admin):
    query = db.query(SubscriptionGroup)
    ids = visible_admin_ids(db, admin)
    if ids is not None:
        if not ids:
            return query.filter(SubscriptionGroup.id < 0)
        query = query.filter(SubscriptionGroup.owner_admin_id.in_(ids))
    return query


def _get_group(db: Session, admin: Admin, group_id: int) -> SubscriptionGroup:
    group = db.get(SubscriptionGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="اشتراک گروهی پیدا نشد.")
    ids = visible_admin_ids(db, admin)
    if ids is not None and group.owner_admin_id not in ids:
        raise HTTPException(status_code=403, detail="این اشتراک در محدودهٔ دسترسی شما نیست.")
    return group


@router.get("", response_model=list[SubscriptionGroupOut])
def list_groups(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.read")),
):
    groups = _scope_groups(db, admin).order_by(SubscriptionGroup.created_at.desc()).all()
    return [build_group_out(group) for group in groups]


@router.post("", response_model=SubscriptionGroupOut, status_code=201)
def create_group(
    payload: SubscriptionGroupCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.write")),
):
    plan = resolve_plan(db, admin, payload.plan_id)
    data = payload.model_dump()
    access_data = {key: data.pop(key) for key in ("allowed_inbound_ids", "allowed_dns_tunnel_ids")}
    data["owner_admin_id"] = admin.id
    data["token"] = secrets.token_urlsafe(24)
    if plan:
        if data["data_limit_bytes"] is None:
            data["data_limit_bytes"] = plan.data_limit_bytes
        if data["expire_at"] is None and plan.days > 0:
            data["expire_at"] = datetime.now(timezone.utc) + timedelta(days=plan.days)
        if data["max_members"] == 1:
            data["max_members"] = max(1, min(100, payload.max_members))
        if admin.require_template:
            data["data_limit_bytes"] = plan.data_limit_bytes
            data["expire_at"] = datetime.now(timezone.utc) + timedelta(days=plan.days) if plan.days else None
    if data["max_members"] < 1:
        raise HTTPException(status_code=400, detail="حداقل یک عضو برای اشتراک لازم است.")
    charge_plan(db, admin, plan)
    group = SubscriptionGroup(**data)
    apply_resource_access(db, group, access_data, admin)
    db.add(group)
    db.commit()
    db.refresh(group)
    write_audit(
        db,
        admin,
        "create_subscription_group",
        "subscription",
        group.id,
        f"ایجاد اشتراک گروهی {group.name}",
        get_client_ip(request),
    )
    return build_group_out(group)


@router.post("/{group_id}/rotate-token", response_model=SubscriptionGroupOut)
def rotate_group_token(group_id: int, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(require_permission("subscriptions.write"))):
    group = _get_group(db, admin, group_id)
    group.token = secrets.token_urlsafe(24)
    db.commit()
    db.refresh(group)
    write_audit(db, admin, "rotate_subscription_token", "subscription", group.id, "ابطال لینک قبلی اشتراک", get_client_ip(request))
    return build_group_out(group)


@router.get("/{group_id}", response_model=SubscriptionGroupOut)
def get_group(
    group_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.read")),
):
    return build_group_out(_get_group(db, admin, group_id))


@router.patch("/{group_id}", response_model=SubscriptionGroupOut)
def update_group(
    group_id: int,
    payload: SubscriptionGroupUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.write")),
):
    group = _get_group(db, admin, group_id)
    data = payload.model_dump(exclude_unset=True)
    apply_resource_access(db, group, data, admin)
    if admin.require_template and any(key in data for key in ("data_limit_bytes", "expire_at", "plan_id")):
        raise HTTPException(status_code=403, detail="تغییر مشخصات پلن برای این نماینده مجاز نیست.")
    if data.get("plan_id"):
        plan = db.get(Plan, data["plan_id"])
        if plan is None:
            raise HTTPException(status_code=404, detail="پلن پیدا نشد.")
    for key, value in data.items():
        setattr(group, key, value)
    if group.max_members < len(group.members):
        raise HTTPException(status_code=400, detail="تعداد اعضای فعلی از سقف جدید بیشتر است.")
    db.commit()
    db.refresh(group)
    write_audit(
        db,
        admin,
        "update_subscription_group",
        "subscription",
        group.id,
        f"ویرایش اشتراک {group.name}",
        get_client_ip(request),
    )
    return build_group_out(group)


@router.delete("/{group_id}", response_model=OperationResult)
def delete_group(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.write")),
):
    group = _get_group(db, admin, group_id)
    db.query(VPNUser).filter(VPNUser.subscription_id == group.id).update(
        {VPNUser.subscription_id: None}, synchronize_session=False
    )
    name = group.name
    db.delete(group)
    db.commit()
    write_audit(
        db,
        admin,
        "delete_subscription_group",
        "subscription",
        group_id,
        f"حذف اشتراک {name}",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="اشتراک حذف شد و اعضا آزاد شدند.")


@router.get("/{group_id}/candidates", response_model=list[UserOut])
def candidates(
    group_id: int,
    search: str | None = None,
    limit: int = 30,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.read")),
):
    group = _get_group(db, admin, group_id)
    query = db.query(VPNUser).filter(
        (VPNUser.subscription_id.is_(None)) | (VPNUser.subscription_id == group.id)
    )
    ids = visible_admin_ids(db, admin)
    if ids is not None:
        query = query.filter(VPNUser.created_by.in_(ids))
    if search:
        query = query.filter(VPNUser.username.ilike(f"%{search}%"))
    users = query.order_by(VPNUser.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return [UserOut.from_user(user) for user in users]


@router.post("/{group_id}/members", response_model=SubscriptionGroupOut)
def add_members(
    group_id: int,
    payload: GroupMembersUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.write")),
):
    group = _get_group(db, admin, group_id)
    users = db.query(VPNUser).filter(VPNUser.id.in_(payload.user_ids)).all()
    if len(users) != len(set(payload.user_ids)):
        raise HTTPException(status_code=404, detail="یکی از کاربران پیدا نشد.")
    for user in users:
        ensure_user_access(db, admin, user)
        if user.subscription_id is not None and user.subscription_id != group.id:
            raise HTTPException(status_code=409, detail=f"کاربر {user.username} عضو اشتراک دیگری است.")
    existing = {member.id for member in group.members}
    new_users = [user for user in users if user.id not in existing]
    if len(group.members) + len(new_users) > group.max_members:
        raise HTTPException(status_code=400, detail="ظرفیت اعضای این اشتراک تکمیل شده است.")
    for user in new_users:
        user.subscription_id = group.id
    db.commit()
    db.refresh(group)
    write_audit(
        db,
        admin,
        "add_subscription_members",
        "subscription",
        group.id,
        f"افزودن {len(new_users)} عضو به {group.name}",
        get_client_ip(request),
    )
    return build_group_out(group)


@router.delete("/{group_id}/members/{user_id}", response_model=SubscriptionGroupOut)
def remove_member(
    group_id: int,
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("subscriptions.write")),
):
    group = _get_group(db, admin, group_id)
    user = db.get(VPNUser, user_id)
    if not user or user.subscription_id != group.id:
        raise HTTPException(status_code=404, detail="این کاربر عضو اشتراک نیست.")
    ensure_user_access(db, admin, user)
    user.subscription_id = None
    db.commit()
    db.refresh(group)
    write_audit(
        db,
        admin,
        "remove_subscription_member",
        "subscription",
        group.id,
        f"حذف {user.username} از {group.name}",
        get_client_ip(request),
    )
    return build_group_out(group)
