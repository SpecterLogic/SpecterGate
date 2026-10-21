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

router = APIRouter(prefix="/amneziawg", tags=["amneziawg"])


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
    current = get_amnezia_params(db)
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
