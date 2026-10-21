from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.deps import get_client_ip, get_db, require_permission
from app.models import Admin, VPNUser
from app.services.amneziawg import (
    AmneziaWgParams,
    client_amnezia_vpn_uri,
    client_awg_config,
    get_amnezia_params,
    randomize_params,
    save_amnezia_params,
    server_awg_config,
)
from app.services.audit import write_audit
from app.services.permissions import ensure_user_access
from app.services import amnezia_runtime

router = APIRouter(prefix="/amneziawg", tags=["amneziawg"])


@router.get("/status")
def native_status(admin: Admin = Depends(require_permission("users.read"))):
    state = amnezia_runtime.server_status()
    return {"ready": bool(state.get("ready")), "port": state.get("port", 51821), "network": "IPv4"}


@router.post("/client/{user_id}/grant")
def grant_access(user_id: int, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(require_permission("settings.manage"))):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    ensure_user_access(db, admin, user)
    if user.status != "active":
        raise HTTPException(409, "User is not active")
    if not amnezia_runtime.server_status().get("ready"):
        raise HTTPException(409, "Install the native AmneziaWG service first.")
    with amnezia_runtime.LOCK:
        amnezia_runtime.provision(db, user)
        db.commit()
        amnezia_runtime.reconcile(db)
    write_audit(db, admin, "grant_amneziawg", "user", user.id, "Native AWG access granted", get_client_ip(request))
    return {"ok": True}


@router.delete("/client/{user_id}/grant")
def revoke_access(user_id: int, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(require_permission("settings.manage"))):
    from app.models import AmneziaPeer
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    ensure_user_access(db, admin, user)
    with amnezia_runtime.LOCK:
        peer = db.query(AmneziaPeer).filter_by(user_id=user_id).first()
        if peer:
            peer.is_active = False
        db.commit()
        amnezia_runtime.reconcile(db)
    write_audit(db, admin, "revoke_amneziawg", "user", user.id, "Native AWG access revoked", get_client_ip(request))
    return {"ok": True}


@router.get("/params", response_model=AmneziaWgParams)
def read_amnezia_params(
    admin: Admin = Depends(require_permission("inbounds.read")),
    db: Session = Depends(get_db),
):
    return get_amnezia_params(db)


@router.put("/params", response_model=AmneziaWgParams)
def update_amnezia_params(
    payload: AmneziaWgParams,
    request: Request,
    admin: Admin = Depends(require_permission("inbounds.manage")),
    db: Session = Depends(get_db),
):
    saved = save_amnezia_params(db, payload)
    write_audit(
        db,
        admin,
        "update_amneziawg_params",
        "amneziawg",
        "global",
        f"پارامترهای مبهم‌سازی AmneziaWG به‌روزرسانی شد: Jc={saved.jc}, Jmin={saved.jmin}, Jmax={saved.jmax}",
        get_client_ip(request),
    )
    return saved


@router.post("/randomize", response_model=AmneziaWgParams)
def randomize_amnezia_params_route(
    request: Request,
    admin: Admin = Depends(require_permission("inbounds.manage")),
    db: Session = Depends(get_db),
):
    try:
        current = get_amnezia_params(db)
    except HTTPException:
        current = None
    randomized = randomize_params(current)
    saved = save_amnezia_params(db, randomized)
    write_audit(
        db,
        admin,
        "randomize_amneziawg_params",
        "amneziawg",
        "global",
        f"پارامترهای مبهم‌سازی AmneziaWG تصادفی‌سازی شد: H1={saved.h1}, H2={saved.h2}, H3={saved.h3}, H4={saved.h4}",
        get_client_ip(request),
    )
    return saved


@router.get("/server-config")
def download_server_config(
    admin: Admin = Depends(require_permission("inbounds.manage")),
    db: Session = Depends(get_db),
):
    content = server_awg_config(db)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=awg0.conf"},
    )


@router.get("/client/{user_id}/config")
def download_client_config(
    user_id: int,
    endpoint: str | None = Query(default=None),
    admin: Admin = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    ensure_user_access(db, admin, user)
    try:
        content = client_awg_config(db, user, endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={quote(user.username)}_awg.conf"},
    )


@router.get("/client/{user_id}/vpn")
def get_client_vpn_uri(
    user_id: int,
    endpoint: str | None = Query(default=None),
    admin: Admin = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    ensure_user_access(db, admin, user)
    try:
        uri = client_amnezia_vpn_uri(db, user, endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {"uri": uri, "username": user.username}
