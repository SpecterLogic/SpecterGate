from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Admin, AdminRole
from app.security import decode_access_token, password_stamp
import hmac
from app.services.permissions import has_permission


oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/token", auto_error=False)


def get_current_admin(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Admin:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="نشست شما معتبر نیست؛ دوباره وارد شوید.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = token or request.cookies.get("spectergate_session")
    if not token:
        raise credentials_error
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise credentials_error from exc

    username = payload.get("sub")
    if not username:
        raise credentials_error
    admin = db.query(Admin).filter(Admin.username == username).first()
    if not admin or not admin.is_active:
        raise credentials_error
    if payload.get("type") != "access" or not hmac.compare_digest(str(payload.get("pwd", "")), password_stamp(admin.password_hash)):
        raise credentials_error
    return admin


def require_roles(*roles: AdminRole) -> Callable:
    allowed = set(roles)

    def dependency(admin: Admin = Depends(get_current_admin)) -> Admin:
        if admin.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی کافی برای این عملیات ندارید.",
            )
        return admin

    return dependency


def require_permission(permission: str) -> Callable:
    def dependency(admin: Admin = Depends(get_current_admin)) -> Admin:
        if not has_permission(admin, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="برای این عملیات مجوز ندارید.",
            )
        return admin

    return dependency


def get_client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
