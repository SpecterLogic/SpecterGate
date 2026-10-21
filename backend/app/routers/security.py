import ipaddress
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin
from app.services import fail2ban
from app.services.audit import write_audit

router = APIRouter(prefix="/security/fail2ban", tags=["security"])


class HostRequest(BaseModel):
    ip: str = Field(min_length=2, max_length=45)


class ProtectionSettings(BaseModel):
    maxretry: int = Field(ge=3, le=20)
    findtime: int = Field(ge=60, le=86400)
    bantime: int = Field(ge=60, le=604800)


def invoke(action, **values):
    try: return fail2ban.command(action, **values)
    except RuntimeError as error: raise HTTPException(503, str(error)) from None


@router.get("")
def status(_: Admin = Depends(require_permission("security.read"))):
    try: return fail2ban.command("status")
    except RuntimeError as error: return {"available": False, "active": False, "message": str(error)}


@router.post("/{action}")
def ban(action: str, payload: HostRequest, request: Request, db: Session = Depends(get_db), actor: Admin = Depends(require_permission("security.manage"))):
    if action not in {"ban", "unban"}: raise HTTPException(404, "Unknown security action")
    try: ip = ipaddress.ip_address(payload.ip)
    except ValueError: raise HTTPException(422, "یک IP معتبر بدون پورت یا CIDR وارد کنید.") from None
    if action == "ban":
        if not ip.is_global or ip.is_multicast: raise HTTPException(422, "مسدودسازی فقط برای IP عمومی مجاز است.")
        client_ip = get_client_ip(request)
        try: current = ipaddress.ip_address(client_ip) if client_ip else None
        except ValueError: current = None
        if ip == current: raise HTTPException(409, "برای جلوگیری از قطع دسترسی، IP نشست فعلی را از داخل پنل مسدود نکنید.")
    result = invoke(action, ip=str(ip))
    write_audit(db, actor, f"fail2ban_{action}", "security", None, str(ip), get_client_ip(request))
    return result


@router.put("")
def configure(payload: ProtectionSettings, request: Request, db: Session = Depends(get_db), actor: Admin = Depends(require_permission("security.manage"))):
    result = invoke("configure", **payload.model_dump())
    write_audit(db, actor, "fail2ban_configure", "security", None, "Updated SSH protection limits", get_client_ip(request))
    return result
