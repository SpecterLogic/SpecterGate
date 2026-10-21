from datetime import datetime, timezone, timedelta
import jwt

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.deps import get_client_ip, get_current_admin
from app.models import Admin, AdminSession, ProtectedSetting
import json
import time
from app.services import two_factor, vault
from app.schemas import AdminOut, ChangePasswordRequest, LoginRequest, TokenResponse, TwoFactorSetupOut, TwoFactorEnableRequest, TwoFactorDisableRequest, OperationResult
from app.services.totp import create_2fa_setup, verify_totp
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
    if admin.totp_enabled:
        if not payload.otp_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="2FA_REQUIRED",
            )
        totp_valid = two_factor.consume(db, admin, payload.otp_code)
        if not totp_valid:
            failed_login(login_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="کد دومرحله‌ای یا کد بازیابی نامعتبر است.",
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


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
def setup_2fa(admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    if admin.totp_enabled:
        raise HTTPException(409, "2FA is already enabled.")
    data = create_2fa_setup(admin.username)
    vault.put_secret(db, f"totp_pending_{admin.id}", json.dumps({**data, "expires": time.time() + 600}))
    db.commit()
    return TwoFactorSetupOut(**data)


@router.post("/2fa/enable", response_model=OperationResult)
def enable_2fa(
    payload: TwoFactorEnableRequest,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if admin.totp_enabled:
        raise HTTPException(status_code=409, detail="ورود دومرحله‌ای از قبل فعال است؛ ابتدا آن را با تأیید رمز عبور غیرفعال کنید.")
    pending = json.loads(vault.get_secret(db, f"totp_pending_{admin.id}") or "{}")
    if pending.get("secret") != payload.secret or pending.get("recovery_codes") != payload.recovery_codes or pending.get("expires", 0) < time.time():
        raise HTTPException(400, "2FA setup expired or does not match this account.")
    if not verify_totp(payload.secret, payload.code):
        raise HTTPException(status_code=400, detail="کد تأیید ۶ رقمی نامعتبر است.")
    vault.put_secret(db, f"totp_{admin.id}", payload.secret)
    admin.totp_secret = f"vault:{admin.id}"
    admin.totp_enabled = True
    admin.recovery_codes_json = json.dumps([two_factor.code_hash(admin.id, code) for code in pending["recovery_codes"]])
    db.delete(db.get(ProtectedSetting, f"totp_pending_{admin.id}"))
    db.query(AdminSession).filter(AdminSession.admin_id == admin.id).delete()
    db.commit()
    write_audit(
        db,
        admin,
        "enable_2fa",
        "admin",
        admin.id,
        "فعال‌سازی ورود دومرحله‌ای (2FA)",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="احراز هویت دومرحله‌ای با موفقیت فعال شد.")


@router.post("/2fa/disable", response_model=OperationResult)
def disable_2fa(
    payload: TwoFactorDisableRequest,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=400, detail="رمز عبور فعلی نادرست است.")
    admin.totp_secret = None
    admin.totp_enabled = False
    admin.recovery_codes_json = None
    two_factor.clear(db, admin)
    db.query(AdminSession).filter(AdminSession.admin_id == admin.id).delete()
    db.commit()
    write_audit(
        db,
        admin,
        "disable_2fa",
        "admin",
        admin.id,
        "غیرفعال‌سازی ورود دومرحله‌ای (2FA)",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="احراز هویت دومرحله‌ای با موفقیت غیرفعال شد.")
