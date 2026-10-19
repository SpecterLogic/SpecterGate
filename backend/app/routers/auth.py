from datetime import datetime, timezone, timedelta
import jwt

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.deps import get_client_ip, get_current_admin
from app.models import Admin, AdminSession
from app.schemas import AdminOut, ChangePasswordRequest, LoginRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password, decode_access_token
from app.services.admin_view import build_admin_out
from app.services.audit import write_audit
from app.services.login_guard import check_login, failed_login, successful_login


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    login_key = f"{get_client_ip(request)}:{payload.username}"
    check_login(login_key)
    admin = db.query(Admin).filter(Admin.username == payload.username).first()
    if admin is None or not admin.is_active or not verify_password(payload.password, admin.password_hash):
        failed_login(login_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="نام کاربری یا رمز عبور نادرست است.",
        )
    successful_login(login_key)
    admin.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(admin)
    token, expires_in = create_access_token(admin.username, admin.role.value, admin.password_hash)
    claims = decode_access_token(token)
    db.query(AdminSession).filter(AdminSession.expires_at < datetime.now(timezone.utc)).delete()
    db.add(AdminSession(id=claims["jti"], admin_id=admin.id, expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in)))
    write_audit(
        db,
        admin,
        "login",
        "admin",
        admin.id,
        "ورود موفق به پنل",
        get_client_ip(request),
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        admin=build_admin_out(db, admin),
    )


@router.post("/session", response_model=AdminOut)
def browser_session(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    result = login(payload, request, db)
    response.set_cookie(
        "spectergate_session", result.access_token, max_age=result.expires_in,
        httponly=True, secure=settings.session_cookie_secure, samesite="strict", path="/api",
    )
    response.headers["Cache-Control"] = "no-store"
    return result.admin


@router.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
    token = bearer if scheme.lower() == "bearer" else request.cookies.get("spectergate_session")
    if token:
        try:
            claims = decode_access_token(token)
            session = db.get(AdminSession, claims["jti"])
            if session:
                db.delete(session)
                db.commit()
        except jwt.PyJWTError:
            pass
    response.delete_cookie("spectergate_session", path="/api", secure=settings.session_cookie_secure, httponly=True, samesite="strict")
    return {"ok": True}


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
def oauth2_token(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 password-flow adapter so Swagger's Authorize button works."""
    return login(LoginRequest(username=form.username, password=form.password), request, db)


@router.get("/me", response_model=AdminOut)
def me(admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return build_admin_out(db, admin)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="رمز عبور فعلی نادرست است.")
    admin.password_hash = hash_password(payload.new_password)
    db.query(AdminSession).filter(AdminSession.admin_id == admin.id).delete()
    db.commit()
    write_audit(
        db,
        admin,
        "change_password",
        "admin",
        admin.id,
        "تغییر رمز عبور",
        get_client_ip(request),
    )
    return {"ok": True, "message": "رمز عبور با موفقیت تغییر کرد."}
