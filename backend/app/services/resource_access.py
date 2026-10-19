"""User and group policies intersect with the administrator's permissions.

None inherits available resources; [] denies all resources of that kind.
Separate tables keep existing database rows intact during this upgrade.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Admin, Inbound, DnsTunnel, VPNUser, UserResourceAccess, GroupResourceAccess


def apply_resource_access(db: Session, target, data: dict, actor: Admin):
    updates = {}
    for key, column, model in [("allowed_inbound_ids", "inbound_ids", Inbound), ("allowed_dns_tunnel_ids", "tunnel_ids", DnsTunnel)]:
        if key not in data:
            continue
        ids = data.pop(key)
        if ids is not None:
            ids = sorted(set(ids))
            if any(i < 1 for i in ids) or db.query(model).filter(model.id.in_(ids)).count() != len(ids):
                raise HTTPException(status_code=404, detail="یکی از کانفیگ‌ها یا تونل‌های انتخاب‌شده پیدا نشد.")
            if model is Inbound and any(not admin_inbound_allowed(actor, i) for i in ids):
                raise HTTPException(status_code=403, detail="این کانفیگ در محدوده دسترسی شما نیست.")
        updates[column] = ids
    if not updates:
        return
    if target.access_policy is None:
        target.access_policy = UserResourceAccess() if isinstance(target, VPNUser) else GroupResourceAccess()
    for key, value in updates.items():
        setattr(target.access_policy, key, value)


def admin_inbound_allowed(admin: Admin, inbound_id: int) -> bool:
    import json
    seen = set()
    while admin is not None and admin.id not in seen:
        seen.add(admin.id)
        if admin.allowed_inbound_ids_json is not None:
            try:
                if inbound_id not in json.loads(admin.allowed_inbound_ids_json):
                    return False
            except (ValueError, TypeError):
                return False
        admin = admin.parent
    return True


def policy_allows(user: VPNUser, resource_id: int, kind: str) -> bool:
    for target in (user, user.subscription):
        if target is not None and target.access_policy is not None:
            ids = getattr(target.access_policy, kind)
            if ids is not None and resource_id not in ids:
                return False
    return True


def tunnel_allowed(user: VPNUser, tunnel_id: int) -> bool:
    return policy_allows(user, tunnel_id, "tunnel_ids")


def remove_resource_references(db: Session, resource_id: int, kind: str):
    for model in (UserResourceAccess, GroupResourceAccess):
        for policy in db.query(model).all():
            ids = getattr(policy, kind)
            if ids is not None and resource_id in ids:
                setattr(policy, kind, [item for item in ids if item != resource_id])
    if kind == "inbound_ids":
        import json
        for admin in db.query(Admin).filter(Admin.allowed_inbound_ids_json.is_not(None)).all():
            ids = json.loads(admin.allowed_inbound_ids_json)
            if resource_id in ids:
                admin.allowed_inbound_ids_json = json.dumps([item for item in ids if item != resource_id])
