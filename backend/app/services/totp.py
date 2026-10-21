from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import urllib.parse
from typing import Any

import qrcode
import qrcode.image.svg


def generate_totp_secret() -> str:
    """Generate a random 32-character base32 secret."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=").upper()


def get_totp_token(
    secret: str, interval: int = 30, digits: int = 6, for_time: int | None = None
) -> str:
    """Compute the RFC 6238 TOTP token for the given secret at a timestamp."""
    if for_time is None:
        for_time = int(time.time())
    counter = int(for_time // interval)
    padded = secret.strip().upper() + "=" * ((8 - len(secret.strip()) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def verify_totp(
    secret: str, token: str, window: int = 1, interval: int = 30, digits: int = 6
) -> bool:
    """Verify a TOTP token against a secret within the allowed time drift window."""
    if not secret or not token or len(token.strip()) != digits:
        return False
    token = token.strip()
    now = int(time.time())
    for w in range(-window, window + 1):
        if get_totp_token(secret, interval, digits, now + w * interval) == token:
            return True
    return False


def get_totp_uri(secret: str, account_name: str, issuer: str = "SpecterGate") -> str:
    """Return the standard otpauth URI."""
    enc_issuer = urllib.parse.quote(issuer)
    enc_account = urllib.parse.quote(account_name)
    return (
        f"otpauth://totp/{enc_issuer}:{enc_account}"
        f"?secret={secret}&issuer={enc_issuer}&algorithm=SHA1&digits=6&period=30"
    )


def generate_recovery_codes(count: int = 8) -> list[str]:
    """Generate single-use backup recovery codes formatted as XXXX-XXXX."""
    codes: list[str] = []
    for _ in range(count):
        token = secrets.token_hex(4).upper()
        codes.append(f"{token[:4]}-{token[4:]}")
    return codes


def generate_qr_svg(uri: str) -> str:
    """Generate SVG image string of the QR code."""
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(uri, image_factory=factory)
    return img.to_string().decode("utf-8") if isinstance(img.to_string(), bytes) else str(img.to_string())


def create_2fa_setup(username: str, issuer: str = "SpecterGate") -> dict[str, Any]:
    """Generate complete 2FA setup bundle: secret, URI, QR SVG, and recovery codes."""
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, username, issuer)
    qr_svg = generate_qr_svg(uri)
    recovery_codes = generate_recovery_codes(8)
    return {
        "secret": secret,
        "uri": uri,
        "qr_svg": qr_svg,
        "recovery_codes": recovery_codes,
    }
