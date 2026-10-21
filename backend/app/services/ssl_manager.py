from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.models import SslCertificate

CERTS_DIR = BASE_DIR / "data" / "certs"


def _clean_domain(domain: str) -> str:
    domain = domain.strip().lower()
    if not domain or "/" in domain or "\\" in domain or ".." in domain or len(domain) > 255:
        raise HTTPException(status_code=400, detail="نام دامنه نامعتبر است.")
    return domain


def inspect_certificate(cert_pem: str) -> dict:
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        issuer_common_name = ""
        for attr in cert.issuer:
            if attr.oid == x509.NameOID.COMMON_NAME:
                issuer_common_name = attr.value
                break
        if not issuer_common_name:
            issuer_common_name = cert.issuer.rfc4514_string()

        # Try not_valid_after_utc or not_valid_after
        try:
            expires_at = cert.not_valid_after_utc
        except AttributeError:
            expires_at = cert.not_valid_after.replace(tzinfo=timezone.utc)

        try:
            issued_at = cert.not_valid_before_utc
        except AttributeError:
            issued_at = cert.not_valid_before.replace(tzinfo=timezone.utc)

        return {
            "issuer": issuer_common_name,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"قالب گواهی SSL (Certificate PEM) نامعتبر است: {exc}") from None


def validate_key_matches_cert(cert_pem: str, key_pem: str) -> None:
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        private_key = serialization.load_pem_private_key(key_pem.encode("utf-8"), password=None)
        
        # Verify public key match
        cert_pub = cert.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        key_pub = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if cert_pub != key_pub:
            raise HTTPException(status_code=400, detail="کلید خصوصی با گواهی SSL بارگذاری‌شده همخوانی ندارد.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"قالب کلید خصوصی (Private Key PEM) نامعتبر است: {exc}") from None


def save_uploaded_certificate(
    db: Session,
    domain: str,
    cert_pem: str,
    key_pem: str,
    auto_renew: bool = False,
) -> SslCertificate:
    domain = _clean_domain(domain)
    validate_key_matches_cert(cert_pem, key_pem)
    details = inspect_certificate(cert_pem)

    dest_dir = CERTS_DIR / domain
    dest_dir.mkdir(parents=True, exist_ok=True)
    cert_path = dest_dir / "fullchain.pem"
    key_path = dest_dir / "privkey.pem"

    cert_path.write_text(cert_pem.strip() + "\n", encoding="utf-8")
    key_path.write_text(key_pem.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass

    record = db.query(SslCertificate).filter_by(domain=domain).first()
    if not record:
        record = SslCertificate(domain=domain)
        db.add(record)

    record.issuer = details["issuer"] or "Custom Upload"
    record.cert_path = str(cert_path.resolve())
    record.key_path = str(key_path.resolve())
    record.issued_at = details["issued_at"]
    record.expires_at = details["expires_at"]
    record.auto_renew = auto_renew
    record.is_active = True
    db.commit()
    db.refresh(record)
    return record


def generate_self_signed_cert(domain: str) -> tuple[str, str]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID
    import datetime

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
    ])
    now = datetime.datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(domain)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return cert_pem, key_pem


def issue_letsencrypt_certificate(
    db: Session,
    domain: str,
    email: str | None = None,
) -> SslCertificate:
    domain = _clean_domain(domain)
    certbot = shutil.which("certbot")

    if certbot:
        cmd = [
            certbot,
            "certonly",
            "--standalone",
            "--non-interactive",
            "--agree-tos",
            "-d",
            domain,
        ]
        if email:
            cmd.extend(["-m", email])
        else:
            cmd.append("--register-unsafely-without-email")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"صدور گواهی Let's Encrypt با خطا مواجه شد. اطمینان حاصل کنید پورت 80 باز است و رکورد DNS به این سرور متصل است: {result.stderr or result.stdout}",
            )

        live_dir = Path(f"/etc/letsencrypt/live/{domain}")
        cert_path = live_dir / "fullchain.pem"
        key_path = live_dir / "privkey.pem"
        if not cert_path.exists():
            raise HTTPException(status_code=500, detail="فایل‌های گواهی صادرشده یافت نشدند.")

        cert_pem = cert_path.read_text(encoding="utf-8")
        details = inspect_certificate(cert_pem)
        record = db.query(SslCertificate).filter_by(domain=domain).first()
        if not record:
            record = SslCertificate(domain=domain)
            db.add(record)
        record.issuer = "Let's Encrypt"
        record.cert_path = str(cert_path)
        record.key_path = str(key_path)
        record.issued_at = details["issued_at"]
        record.expires_at = details["expires_at"]
        record.auto_renew = True
        record.is_active = True
        db.commit()
        db.refresh(record)
        return record
    else:
        # Fallback in environments without certbot (e.g. testing / local development)
        cert_pem, key_pem = generate_self_signed_cert(domain)
        return save_uploaded_certificate(db, domain, cert_pem, key_pem, auto_renew=False)


def delete_certificate(db: Session, cert_id: int) -> bool:
    cert = db.get(SslCertificate, cert_id)
    if not cert:
        return False
    # If in app data certs dir, remove files
    try:
        p = Path(cert.cert_path)
        if CERTS_DIR in p.parents:
            shutil.rmtree(p.parent, ignore_errors=True)
    except Exception:
        pass

    db.delete(cert)
    db.commit()
    return True
