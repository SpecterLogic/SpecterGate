from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, get_current_admin, require_permission
from app.models import Admin, AdminRole, CreditTransaction, VPNUser
from app.schemas import (
    AdminCreate,
    AdminOut,
    AdminUpdate,
    CreditAdjustment,
    CreditTransactionOut,
    OperationResult,
)
from app.security import hash_password
from app.services.admin_view import build_admin_out
from app.services.audit import write_audit
from app.services.permissions import ALL_PERMISSIONS, adjust_credit, permissions_for, visible_admin_ids, descendant_ids


router = APIRouter(prefix="/admins", tags=["admins"])
manage_access = require_permission("admins.manage")
read_access = require_permission("admins.read")


def ensure_admin_access(db: Session, actor: Admin, target: Admin):
    ids = visible_admin_ids(db, actor)
    if ids is not None and target.id not in ids:
        raise HTTPException(status_code=403, detail="این ادمین در محدوده دسترسی شما نیست.")


def validate_delegation(db: Session, actor: Admin, payload, target: Admin | None = None):
    data = payload.model_dump(exclude_unset=True)
    if not actor.is_owner:
        if target and target.id == actor.id and any(key != "password" for key in data):
            raise HTTPException(status_code=403, detail="امکان تغییر مجوزها و سهمیه حساب خودتان را ندارید.")
        if "parent_id" in data and data["parent_id"] is None and target is not None:
            raise HTTPException(status_code=403, detail="حذف ادمین بالادستی فقط توسط مالک مجاز است.")
        if target and (target.is_owner or target.role == AdminRole.superadmin):
            raise HTTPException(status_code=403, detail="ویرایش مدیر کل فقط توسط مالک مجاز است.")
        if data.get("role") == "superadmin":
            raise HTTPException(status_code=403, detail="فقط مالک می‌تواند مدیر کل تعریف کند.")
        if "permissions" in data or "role" in data or target is None:
            from app.services.permissions import DEFAULT_PERMISSIONS
            role = AdminRole(data.get("role") or (target.role if target else "reseller"))
            requested = data.get("permissions") or DEFAULT_PERMISSIONS[role]
            if not set(requested).issubset(permissions_for(actor)):
                raise HTTPException(status_code=403, detail="امکان واگذاری مجوزی بالاتر از مجوزهای خودتان را ندارید.")
        if data.get("scope") == "all" and visible_admin_ids(db, actor) is not None:
            raise HTTPException(status_code=403, detail="امکان واگذاری دسترسی به همه کاربران را ندارید.")
        if data.get("credit", 0):
            raise HTTPException(status_code=403, detail="برای شارژ اعتبار از عملیات اعتبار استفاده کنید.")
    if data.get("parent_id") is not None:
        parent = db.get(Admin, data["parent_id"])
        if parent is None:
            raise HTTPException(status_code=404, detail="ادمین بالادستی پیدا نشد.")
        ensure_admin_access(db, actor, parent)
        if target and parent.id in descendant_ids(db, target):
            raise HTTPException(status_code=400, detail="ساخت چرخه در سلسله مراتب مجاز نیست.")


@router.get("", response_model=list[AdminOut])
def list_admins(db: Session = Depends(get_db), actor: Admin = Depends(read_access)):
    query = db.query(Admin)
    ids = visible_admin_ids(db, actor)
    if ids is not None:
        query = query.filter(Admin.id.in_(ids))
    admins = query.order_by(Admin.is_owner.desc(), Admin.created_at.asc()).all()
    return [build_admin_out(db, admin) for admin in admins]


@router.post("", response_model=AdminOut, status_code=201)
def create_admin(
    payload: AdminCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(manage_access),
):
    validate_delegation(db, actor, payload)
    if db.query(Admin).filter(Admin.username == payload.username).first():
        raise HTTPException(status_code=409, detail="این نام کاربری قبلاً ثبت شده است.")
    if payload.role == AdminRole.superadmin and not actor.is_owner:
        raise HTTPException(status_code=403, detail="فقط مالک می‌تواند ادمین کل بسازد.")
    if payload.parent_id is not None and db.get(Admin, payload.parent_id) is None:
        raise HTTPException(status_code=404, detail="ادمین بالادستی پیدا نشد.")

    admin = Admin(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=AdminRole(payload.role),
        parent_id=payload.parent_id if payload.parent_id is not None else actor.id,
        scope=payload.scope,
        max_users=payload.max_users,
        traffic_quota_bytes=payload.traffic_quota_bytes,
        credit=payload.credit,
        require_template=payload.require_template,
        permissions_json=json.dumps(payload.permissions, ensure_ascii=False)
        if payload.permissions
        else None,
        allowed_inbound_ids_json=json.dumps(payload.allowed_inbound_ids) if payload.allowed_inbound_ids is not None else None,
        is_active=payload.is_active,
    )
    db.add(admin)
    db.flush()
    if payload.credit:
        db.add(CreditTransaction(admin_id=admin.id, amount=payload.credit, balance_after=payload.credit, kind="opening_balance", created_by=actor.id))
    db.commit()
    db.refresh(admin)
    write_audit(
        db,
        actor,
        "create_admin",
        "admin",
        admin.id,
        f"ایجاد ادمین {admin.username} با نقش {admin.role.value}",
        get_client_ip(request),
    )
    return build_admin_out(db, admin)


@router.get("/{admin_id}", response_model=AdminOut)
def get_admin(admin_id: int, db: Session = Depends(get_db), actor: Admin = Depends(read_access)):
    admin = db.get(Admin, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="ادمین پیدا نشد.")
    ensure_admin_access(db, actor, admin)
    return build_admin_out(db, admin)


@router.patch("/{admin_id}", response_model=AdminOut)
def update_admin(
    admin_id: int,
    payload: AdminUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(manage_access),
):
    admin = db.get(Admin, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="ادمین پیدا نشد.")
    ensure_admin_access(db, actor, admin)
    validate_delegation(db, actor, payload, admin)
    if admin.is_owner and any(key != "password" for key in payload.model_fields_set):
        raise HTTPException(status_code=403, detail="تنها رمز حساب مالک قابل تغییر است.")
    if admin.is_owner and admin.id != actor.id:
        raise HTTPException(status_code=403, detail="حساب مالک قابل ویرایش نیست.")
    if admin.id == actor.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="نمی‌توانید حساب خودتان را غیرفعال کنید.")
    if payload.role == AdminRole.superadmin and not actor.is_owner:
        raise HTTPException(status_code=403, detail="فقط مالک می‌تواند نقش ادمین کل بدهد.")
    if payload.parent_id == admin.id:
        raise HTTPException(status_code=400, detail="ادمین نمی‌تواند بالادستی خودش باشد.")

    data = payload.model_dump(exclude_unset=True)
    if "credit" in data:
        amount = data.pop("credit")
        if amount is None:
            raise HTTPException(status_code=422, detail="اعتبار نمی‌تواند خالی باشد.")
        adjust_credit(db, admin, amount - admin.credit, actor, "تنظیم اعتبار از ویرایش ادمین")
    if "password" in data:
        admin.password_hash = hash_password(data.pop("password"))
    if "allowed_inbound_ids" in data:
        inbound_ids = data.pop("allowed_inbound_ids")
        admin.allowed_inbound_ids_json = json.dumps(inbound_ids) if inbound_ids is not None else None
    if "permissions" in data:
        permissions = data.pop("permissions")
        admin.permissions_json = json.dumps(permissions, ensure_ascii=False) if permissions else None
    if "role" in data and data["role"] is not None:
        admin.role = AdminRole(data.pop("role"))
    for key, value in data.items():
        if key == "is_owner":
            continue
        setattr(admin, key, value)
    db.commit()
    db.refresh(admin)
    write_audit(
        db,
        actor,
        "update_admin",
        "admin",
        admin.id,
        f"ویرایش ادمین {admin.username}",
        get_client_ip(request),
    )
    return build_admin_out(db, admin)


@router.delete("/{admin_id}", response_model=OperationResult)
def delete_admin(
    admin_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(manage_access),
):
    admin = db.get(Admin, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="ادمین پیدا نشد.")
    ensure_admin_access(db, actor, admin)
    if admin.role == AdminRole.superadmin and not actor.is_owner:
        raise HTTPException(status_code=403, detail="حذف مدیر کل فقط توسط مالک مجاز است.")
    if admin.is_owner:
        raise HTTPException(status_code=403, detail="حساب مالک قابل حذف نیست.")
    if admin.id == actor.id:
        raise HTTPException(status_code=400, detail="نمی‌توانید حساب خودتان را حذف کنید.")
    db.query(VPNUser).filter(VPNUser.created_by == admin.id).update(
        {VPNUser.created_by: actor.id}, synchronize_session=False
    )
    username = admin.username
    db.delete(admin)
    db.commit()
    write_audit(
        db,
        actor,
        "delete_admin",
        "admin",
        admin_id,
        f"حذف ادمین {username}",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="ادمین حذف شد و کاربرانش به حساب شما منتقل شدند.")


@router.post("/{admin_id}/credit", response_model=CreditTransactionOut)
def adjust_admin_credit(
    admin_id: int,
    payload: CreditAdjustment,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(require_permission("credits.manage")),
):
    if not actor.is_owner:
        raise HTTPException(status_code=403, detail="تغییر موجودی فقط توسط مالک مجاز است.")
    admin = db.get(Admin, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="ادمین پیدا نشد.")
    transaction = adjust_credit(db, admin, payload.amount, actor, payload.note)
    db.commit()
    db.refresh(transaction)
    write_audit(
        db,
        actor,
        "adjust_credit",
        "admin",
        admin.id,
        f"تغییر اعتبار {admin.username}: {payload.amount}",
        get_client_ip(request),
    )
    return transaction


@router.get("/{admin_id}/transactions", response_model=list[CreditTransactionOut])
def credit_transactions(
    admin_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    actor: Admin = Depends(read_access),
):
    target = db.get(Admin, admin_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ادمین پیدا نشد.")
    ensure_admin_access(db, actor, target)
    limit = max(1, min(limit, 200))
    return (
        db.query(CreditTransaction)
        .filter(CreditTransaction.admin_id == admin_id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/meta/permissions", response_model=list[str])
def list_permissions(_: Admin = Depends(read_access)):
    return ALL_PERMISSIONS
