from __future__ import annotations

import os
import re
import shutil
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
    if len(domain) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in domain.split(".")
    ):
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
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cert_path = dest_dir / "fullchain.pem"
    key_path = dest_dir / "privkey.pem"

    cert_path.write_text(cert_pem.strip() + "\n", encoding="utf-8")
    # Restrict the descriptor before writing any private key bytes.
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.chmod(key_path, 0o600)
        stream.write(key_pem.strip() + "\n")

    record = db.query(SslCertificate).filter_by(domain=domain).first()
    if not record:
        record = SslCertificate(domain=domain)
        db.add(record)

    record.issuer = details["issuer"] or "Custom Upload"
    record.cert_path = str(cert_path.resolve())
    record.key_path = str(key_path.resolve())
    record.issued_at = details["issued_at"]
    record.expires_at = details["expires_at"]
    record.auto_renew = False  # Uploaded files have no Certbot renewal lineage.
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
    from app.services.ssl_worker import issue
    try:
        result = issue(domain, email)
        cert_path = Path(result["cert_path"])
        key_path = Path(result["key_path"])
        expected = Path("/var/lib/spectergate-certificates") / domain
        if cert_path.parent != expected or key_path.parent != expected:
            raise ValueError("Unexpected certificate path")
        cert_pem = cert_path.read_text(encoding="utf-8")
        validate_key_matches_cert(cert_pem, key_path.read_text(encoding="utf-8"))
        details = inspect_certificate(cert_pem)
    except (RuntimeError, OSError, KeyError, ValueError):
        raise HTTPException(503, "Certificate worker unavailable or issuance failed; install deploy/ssl_install.sh and check DNS/TCP 80.") from None
    record = db.query(SslCertificate).filter_by(domain=domain).first()
    if not record:
        record = SslCertificate(domain=domain)
        db.add(record)
    record.issuer = "Let's Encrypt"
    record.cert_path, record.key_path = str(cert_path), str(key_path)
    record.issued_at, record.expires_at = details["issued_at"], details["expires_at"]
    record.auto_renew, record.is_active = True, True
    db.commit()
    db.refresh(record)
    return record


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
