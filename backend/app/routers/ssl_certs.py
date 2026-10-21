from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.deps import get_client_ip, get_db, require_permission
from app.models import Admin, SslCertificate, as_utc
from app.services.audit import write_audit
from app.services.ssl_manager import (
    delete_certificate,
    issue_letsencrypt_certificate,
    save_uploaded_certificate,
)

router = APIRouter(prefix="/certificates", tags=["certificates"])


class SslCertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    issuer: str
    cert_path: str
    key_path: str
    issued_at: datetime
    expires_at: datetime | None
    auto_renew: bool
    is_active: bool
    days_remaining: int | None = None


class CertUploadRequest(BaseModel):
    domain: str = Field(..., max_length=255)
    cert_pem: str = Field(..., min_length=20)
    key_pem: str = Field(..., min_length=20)
    auto_renew: bool = False


class CertIssueRequest(BaseModel):
    domain: str = Field(..., max_length=255)
    email: str | None = None


def _days_remaining(expires_at: datetime | None) -> int | None:
    if not expires_at:
        return None
    now = datetime.now(timezone.utc)
    exp = as_utc(expires_at)
    return (exp - now).days if exp else None


@router.get("", response_model=list[SslCertOut])
def list_certificates(
    admin: Admin = Depends(require_permission("settings.read")),
    db: Session = Depends(get_db),
):
    certs = db.query(SslCertificate).order_by(SslCertificate.id.desc()).all()
    results = []
    for c in certs:
        out = SslCertOut(
            id=c.id,
            domain=c.domain,
            issuer=c.issuer,
            cert_path=c.cert_path,
            key_path=c.key_path,
            issued_at=c.issued_at,
            expires_at=c.expires_at,
            auto_renew=c.auto_renew,
            is_active=c.is_active,
            days_remaining=_days_remaining(c.expires_at),
        )
        results.append(out)
    return results


@router.post("/upload", response_model=SslCertOut)
def upload_certificate(
    payload: CertUploadRequest,
    request: Request,
    admin: Admin = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    cert = save_uploaded_certificate(
        db,
        domain=payload.domain,
        cert_pem=payload.cert_pem,
        key_pem=payload.key_pem,
        auto_renew=payload.auto_renew,
    )
    write_audit(
        db,
        admin,
        "upload_ssl_certificate",
        "ssl_certificate",
        payload.domain,
        f"گواهی SSL دستی برای دامنه {payload.domain} بارگذاری شد.",
        get_client_ip(request),
    )
    return SslCertOut(
        id=cert.id,
        domain=cert.domain,
        issuer=cert.issuer,
        cert_path=cert.cert_path,
        key_path=cert.key_path,
        issued_at=cert.issued_at,
        expires_at=cert.expires_at,
        auto_renew=cert.auto_renew,
        is_active=cert.is_active,
        days_remaining=_days_remaining(cert.expires_at),
    )


@router.post("/issue", response_model=SslCertOut)
def issue_certificate(
    payload: CertIssueRequest,
    request: Request,
    admin: Admin = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    cert = issue_letsencrypt_certificate(db, domain=payload.domain, email=payload.email)
    write_audit(
        db,
        admin,
        "issue_ssl_certificate",
        "ssl_certificate",
        payload.domain,
        f"صدور گواهی SSL Let's Encrypt برای دامنه {payload.domain} با موفقیت انجام شد.",
        get_client_ip(request),
    )
    return SslCertOut(
        id=cert.id,
        domain=cert.domain,
        issuer=cert.issuer,
        cert_path=cert.cert_path,
        key_path=cert.key_path,
        issued_at=cert.issued_at,
        expires_at=cert.expires_at,
        auto_renew=cert.auto_renew,
        is_active=cert.is_active,
        days_remaining=_days_remaining(cert.expires_at),
    )


@router.delete("/{cert_id}")
def delete_ssl_certificate(
    cert_id: int,
    request: Request,
    admin: Admin = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    cert = db.get(SslCertificate, cert_id)
    if not cert:
        raise HTTPException(status_code=404, detail="گواهی یافت نشد.")
    domain = cert.domain
    delete_certificate(db, cert_id)
    write_audit(
        db,
        admin,
        "delete_ssl_certificate",
        "ssl_certificate",
        domain,
        f"گواهی SSL دامنه {domain} حذف شد.",
        get_client_ip(request),
    )
    return {"ok": True}
