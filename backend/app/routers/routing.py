from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Admin
from app.deps import get_client_ip
from app.routers.integrations import owner_only
from app.services.routing import RoutingUpdate, read_config, write_config, verify_node
from app.services.audit import write_audit

router = APIRouter(prefix="/routing", tags=["routing"])


@router.get("")
def get_routing(node_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db), _: Admin = Depends(owner_only)):
    verify_node(db, node_id)
    return read_config(db, node_id)


@router.put("")
def update_routing(payload: RoutingUpdate, request: Request, node_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    write_config(db, payload, node_id)
    db.commit()
    write_audit(db, actor, "update_routing", "routing", node_id, "تنظیم خروجی‌های Direct/WARP/Block", get_client_ip(request))
    return read_config(db, node_id)
