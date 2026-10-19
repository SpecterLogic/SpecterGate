from sqlalchemy.orm import Session
import json

from app.models import Admin
from app.schemas import AdminOut
from app.services.permissions import permissions_for, usage_for


def build_admin_out(db: Session, admin: Admin) -> AdminOut:
    output = AdminOut.model_validate(admin)
    output.permissions = permissions_for(admin)
    output.allowed_inbound_ids = json.loads(admin.allowed_inbound_ids_json) if admin.allowed_inbound_ids_json is not None else None
    user_count, traffic = usage_for(db, admin)
    output.user_count = user_count
    output.used_traffic_bytes = traffic
    return output
