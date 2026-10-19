from sqlalchemy.orm import Session

from app.models import Admin, AuditLog


def write_audit(
    db: Session,
    admin: Admin | None,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id if admin else None,
            admin_username=admin.username if admin else "system",
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
            ip_address=ip_address,
        )
    )
    db.commit()
