from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Admin
from app.deps import get_client_ip, require_permission
from app.services.routing import RoutingUpdate, RoutingConfig, ProxyOutboundUpdate, read_config, write_config, verify_node, outbound_secret
from app.services.vault import put_secret
from app.models import ProtectedSetting
from pydantic import BaseModel, Field
from fastapi import HTTPException
from app.services.audit import write_audit
from app.services.warp_client import register_warp_account

router = APIRouter(prefix="/routing", tags=["routing"])


class OutboundsUpdate(BaseModel):
    outbounds: list[ProxyOutboundUpdate] = Field(max_length=20)
    default_outbound: str


@router.put("/outbounds")
def update_outbounds(payload: OutboundsUpdate, request: Request, node_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db), actor: Admin = Depends(require_permission("routing.manage"))):
    verify_node(db, node_id)
    current = read_config(db, node_id)
    profiles = [item.model_dump(exclude={"password"}) for item in payload.outbounds]
    try: merged = RoutingUpdate.model_validate({**current, "outbounds": profiles, "default_outbound": payload.default_outbound})
    except ValueError: raise HTTPException(422, "خروجی نامعتبر است یا هنوز در قوانین مسیریابی استفاده می‌شود.") from None
    for item in payload.outbounds:
        if item.password is not None:
            password = item.password.get_secret_value()
            if len(password) > 256: raise HTTPException(422, "رمز خروجی بیش از حد طولانی است.")
            put_secret(db, outbound_secret(item.tag, node_id), password)
    db.flush()
    write_config(db, merged, node_id)
    retained = {item.tag for item in payload.outbounds}
    for old in current["outbounds"]:
        if old["tag"] not in retained:
            row = db.get(ProtectedSetting, outbound_secret(old["tag"], node_id))
            if row: db.delete(row)
    db.commit()
    write_audit(db, actor, "update_outbounds", "routing", node_id, "Updated outbound profiles", get_client_ip(request))
    return read_config(db, node_id)


@router.get("")
def get_routing(node_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db), _: Admin = Depends(require_permission("routing.read"))):
    verify_node(db, node_id)
    return read_config(db, node_id)


@router.put("")
def update_routing(payload: RoutingUpdate, request: Request, node_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db), actor: Admin = Depends(require_permission("routing.manage"))):
    # Proxy profiles have their own endpoint; a stale rule editor must not erase them.
    current = read_config(db, node_id)
    try: payload = RoutingUpdate.model_validate({**payload.model_dump(), "outbounds": current["outbounds"]})
    except ValueError: raise HTTPException(422, "خروجی یکی از قوانین تغییر کرده است؛ صفحه را تازه کنید.") from None
    write_config(db, payload, node_id)
    db.commit()
    write_audit(db, actor, "update_routing", "routing", node_id, "تنظیم خروجی‌های Direct/WARP/Block", get_client_ip(request))
    return read_config(db, node_id)


@router.post("/warp/auto-register")
def auto_register_warp(
    request: Request,
    node_id: int | None = Query(default=None, ge=1),
    allow_fallback: bool = Query(default=True),
    db: Session = Depends(get_db),
    actor: Admin = Depends(require_permission("routing.manage")),
):
    verify_node(db, node_id)
    result = register_warp_account(allow_fallback=allow_fallback)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("message", "ثبت حساب WARP ناموفق بود."))

    write_audit(
        db,
        actor,
        "register_warp",
        "routing",
        node_id,
        "ثبت ۱-کلیکی حساب Cloudflare WARP",
        get_client_ip(request),
    )
    return result
