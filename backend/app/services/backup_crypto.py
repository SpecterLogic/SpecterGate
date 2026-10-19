"""Portable authenticated backup encryption; no application configuration required."""
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"SGBK1"


def encrypt_archive(payload: bytes, password: str) -> bytes:
    if len(password) < 16:
        raise ValueError("Backup password must have at least 16 characters.")
    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())
    return MAGIC + salt + nonce + AESGCM(key).encrypt(nonce, payload, MAGIC)


def decrypt_archive(payload: bytes, password: str) -> bytes:
    if not payload.startswith(MAGIC) or len(payload) < 49:
        raise ValueError("Not a SpecterGate encrypted backup.")
    salt, nonce = payload[5:21], payload[21:33]
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())
    return AESGCM(key).decrypt(nonce, payload[33:], MAGIC)
