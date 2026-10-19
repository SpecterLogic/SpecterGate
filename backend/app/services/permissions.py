"""Role, scope, quota and reseller-credit rules."""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models import Admin, AdminRole, CreditTransaction, Plan, VPNUser


ALL_PERMISSIONS = [
    "dashboard.read",
    "users.read",
    "users.write",
    "users.delete",
    "subscriptions.read",
    "subscriptions.write",
    "plans.read",
    "plans.manage",
    "admins.read",
    "admins.manage",
    "credits.manage",
    "nodes.read",
    "nodes.manage",
    "inbounds.read",
    "inbounds.manage",
    "dns.read",
    "dns.manage",
    "xray.manage",
    "settings.read",
    "settings.manage",
    "audit.read",
]

DEFAULT_PERMISSIONS: dict[AdminRole, list[str]] = {
    AdminRole.superadmin: ALL_PERMISSIONS,
    AdminRole.admin: [
        "dashboard.read",
        "users.read",
        "users.write",
        "users.delete",
        "subscriptions.read",
        "subscriptions.write",
        "plans.read",
        "plans.manage",
        "nodes.read",
        "nodes.manage",
        "inbounds.read",
        "inbounds.manage",
        "dns.read",
        "dns.manage",
        "xray.manage",
        "settings.read",
        "audit.read",
    ],
    AdminRole.reseller: [
        "dashboard.read",
        "users.read",
        "users.write",
        "users.delete",
        "subscriptions.read",
        "subscriptions.write",
        "plans.read",
    ],
    AdminRole.support: ["dashboard.read", "users.read", "subscriptions.read"],
    AdminRole.viewer: ["dashboard.read", "users.read", "inbounds.read", "nodes.read", "subscriptions.read"],
}


def permissions_for(admin: Admin) -> list[str]:
    if admin.is_owner or admin.role == AdminRole.superadmin:
        return list(ALL_PERMISSIONS)
    if admin.permissions_json:
        try:
            custom = json.loads(admin.permissions_json)
            if isinstance(custom, list):
                return [str(item) for item in custom if str(item) in ALL_PERMISSIONS]
        except (json.JSONDecodeError, TypeError):
            pass
    return list(DEFAULT_PERMISSIONS.get(admin.role, []))


def has_permission(admin: Admin, permission: str) -> bool:
    return permission in permissions_for(admin)


def account_status(db: Session, admin: Admin) -> str:
    seen = set()
    current = admin
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if not current.is_active:
            return "disabled"
        if not current.is_owner and current.traffic_quota_bytes is not None:
            _, traffic = usage_for(db, current)
            if traffic >= current.traffic_quota_bytes:
                return "limited"
        current = current.parent
    return "active"


def inbound_allowed(user: VPNUser, inbound_id: int) -> bool:
    from app.services.resource_access import policy_allows, admin_inbound_allowed
    if not policy_allows(user, inbound_id, "inbound_ids"):
        return False
    if user.subscription and user.subscription.owner and not admin_inbound_allowed(user.subscription.owner, inbound_id):
        return False
    current = user.creator
    seen = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.allowed_inbound_ids_json is not None:
            try:
                if inbound_id not in json.loads(current.allowed_inbound_ids_json):
                    return False
            except (ValueError, TypeError):
                return False
        current = current.parent
    return True


def require(admin: Admin, permission: str) -> None:
    if not has_permission(admin, permission):
        raise HTTPException(status_code=403, detail="برای این عملیات مجوز ندارید.")


def descendant_ids(db: Session, admin: Admin) -> list[int]:
    """Return the admin and all administrators below it (cycle-safe)."""
    result = [admin.id]
    frontier = [admin.id]
    seen = {admin.id}
    while frontier:
        rows = db.query(Admin.id).filter(Admin.parent_id.in_(frontier)).all()
        frontier = []
        for (admin_id,) in rows:
            if admin_id not in seen:
                seen.add(admin_id)
                result.append(admin_id)
                frontier.append(admin_id)
    return result


def visible_admin_ids(db: Session, admin: Admin) -> list[int] | None:
    """None means every administrator/user is visible."""
    if admin.is_owner or admin.role == AdminRole.superadmin or admin.scope == "all":
        return None
    if admin.scope == "none":
        return []
    return descendant_ids(db, admin)


def user_query_for(db: Session, admin: Admin):
    query = db.query(VPNUser)
    ids = visible_admin_ids(db, admin)
    if ids is not None:
        if not ids:
            return query.filter(VPNUser.id < 0)
        query = query.filter(VPNUser.created_by.in_(ids))
    return query


def ensure_user_access(db: Session, admin: Admin, user: VPNUser) -> None:
    ids = visible_admin_ids(db, admin)
    if ids is not None and user.created_by not in ids:
        raise HTTPException(status_code=403, detail="این کاربر در محدودهٔ دسترسی شما نیست.")


def can_assign_owner(db: Session, admin: Admin, owner_admin_id: int | None) -> int:
    if owner_admin_id is None:
        return admin.id
    if visible_admin_ids(db, admin) is not None and owner_admin_id not in (visible_admin_ids(db, admin) or []):
        raise HTTPException(status_code=403, detail="امکان تخصیص کاربر به این ادمین را ندارید.")
    target = db.get(Admin, owner_admin_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ادمین مالک پیدا نشد.")
    return target.id


def usage_for(db: Session, admin: Admin) -> tuple[int, int]:
    ids = visible_admin_ids(db, admin)
    query = db.query(
        func.count(VPNUser.id),
        func.coalesce(func.sum(VPNUser.upload_bytes + VPNUser.download_bytes), 0),
    )
    if ids is not None:
        if not ids:
            return 0, 0
        query = query.filter(VPNUser.created_by.in_(ids))
    count, traffic = query.one()
    return int(count or 0), int(traffic or 0)


def enforce_user_quota(db: Session, admin: Admin) -> None:
    if admin.is_owner or admin.role == AdminRole.superadmin:
        return
    if admin.scope == "none":
        raise HTTPException(status_code=403, detail="سطح دسترسی شما اجازهٔ ساخت کاربر ندارد.")
    count, traffic = usage_for(db, admin)
    if admin.max_users is not None and count >= admin.max_users:
        raise HTTPException(status_code=403, detail="سهمیهٔ تعداد کاربران شما تکمیل شده است.")
    if admin.traffic_quota_bytes is not None and traffic >= admin.traffic_quota_bytes:
        raise HTTPException(status_code=403, detail="سهمیهٔ ترافیک شما تکمیل شده است.")
    seen = {admin.id}
    parent = admin.parent
    while parent is not None and parent.id not in seen:
        seen.add(parent.id)
        if not parent.is_active:
            raise HTTPException(status_code=403, detail="ادمین بالادستی غیرفعال است.")
        count, traffic = usage_for(db, parent)
        if not parent.is_owner and (
            (parent.max_users is not None and count >= parent.max_users)
            or (parent.traffic_quota_bytes is not None and traffic >= parent.traffic_quota_bytes)
        ):
            raise HTTPException(status_code=403, detail="سهمیه ادمین بالادستی تکمیل شده است.")
        parent = parent.parent


def resolve_plan(db: Session, admin: Admin, plan_id: int | None) -> Plan | None:
    if admin.require_template and plan_id is None:
        raise HTTPException(status_code=400, detail="برای این ادمین انتخاب یک پلن الزامی است.")
    if plan_id is None:
        return None
    plan = db.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=404, detail="پلن انتخاب‌شده فعال نیست.")
    return plan


def charge_plan(db: Session, admin: Admin, plan: Plan | None) -> int:
    """Deduct a plan price from a reseller's credit. Owners are not charged."""
    if plan is None or plan.price <= 0:
        return 0
    if admin.is_owner or admin.role in {AdminRole.superadmin, AdminRole.support, AdminRole.viewer}:
        return 0
    balance = db.execute(update(Admin).where(Admin.id == admin.id, Admin.credit >= plan.price).values(credit=Admin.credit - plan.price).returning(Admin.credit)).scalar_one_or_none()
    if balance is None:
        raise HTTPException(status_code=402, detail="اعتبار کافی برای خرید این پلن وجود ندارد.")
    admin.credit = balance
    db.add(
        CreditTransaction(
            admin_id=admin.id,
            amount=-plan.price,
            balance_after=admin.credit,
            kind="plan_purchase",
            note=f"ساخت کاربر با پلن {plan.name}",
            created_by=admin.id,
        )
    )
    return plan.price


def adjust_credit(db: Session, admin: Admin, amount: int, actor: Admin, note: str | None = None) -> CreditTransaction:
    new_balance = db.execute(update(Admin).where(Admin.id == admin.id, Admin.credit + amount >= 0).values(credit=Admin.credit + amount).returning(Admin.credit)).scalar_one_or_none()
    if new_balance is None:
        raise HTTPException(status_code=400, detail="موجودی ادمین نمی‌تواند منفی شود.")
    admin.credit = new_balance
    transaction = CreditTransaction(
        admin_id=admin.id,
        amount=amount,
        balance_after=new_balance,
        kind="topup" if amount >= 0 else "withdrawal",
        note=note,
        created_by=actor.id,
    )
    db.add(transaction)
    return transaction
