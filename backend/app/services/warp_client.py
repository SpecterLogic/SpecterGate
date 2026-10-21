from __future__ import annotations

import base64
import logging
import ipaddress
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519
import httpx

logger = logging.getLogger(__name__)

CF_REG_ENDPOINTS = [
    "https://api.cloudflareclient.com/v0a2158/reg",
    "https://api.cloudflareclient.com/v0a884/reg",
    "https://api.cloudflareclient.com/v0a745/reg",
]
DEFAULT_CF_PUBLIC_KEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
DEFAULT_ENDPOINT = "engage.cloudflareclient.com:2408"


def generate_wireguard_keypair() -> tuple[str, str]:
    """Generate a standard base64 WireGuard (x25519) private and public key pair."""
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub_bytes = pub.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_bytes).decode("ascii"), base64.b64encode(pub_bytes).decode("ascii")


def register_warp_account(
    peer_endpoint: str = DEFAULT_ENDPOINT,
    timeout_seconds: float = 3.0,
    allow_fallback: bool = False,
) -> dict[str, Any]:
    """
    Register a new Cloudflare WARP account via the official client registration API.
    Returns the generated private key, peer public key, reserved bytes, and assigned IPs.
    """
    private_key, public_key = generate_wireguard_keypair()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payload = {
        "key": public_key,
        "install_id": "",
        "fcm_token": "",
        "tos": now_iso,
        "model": "PC",
        "type": "Android",
        "locale": "en_US",
    }
    headers = {
        "User-Agent": "okhttp/3.12.1",
        "Content-Type": "application/json; charset=UTF-8",
    }

    last_error = None
    for endpoint in CF_REG_ENDPOINTS:
        try:
            with httpx.Client(timeout=timeout_seconds, verify=True) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    if not isinstance(data, dict) or not data.get("id") or not data.get("token"):
                        raise ValueError("Incomplete Cloudflare account response")
                    config = data.get("config", {})
                    interface = config.get("interface", {})
                    addresses_obj = interface.get("addresses", {})

                    v4 = addresses_obj.get("v4")
                    v6 = addresses_obj.get("v6")
                    addresses = []
                    if v4:
                        addresses.append(v4 if "/" in v4 else f"{v4}/32")
                    if v6:
                        addresses.append(v6 if "/" in v6 else f"{v6}/128")
                    if not addresses:
                        raise ValueError("Cloudflare did not assign interface addresses")
                    for address in addresses:
                        ipaddress.ip_interface(address)

                    # Reserved 3 bytes from client_id
                    client_id_raw = config.get("client_id", "")
                    decoded = base64.b64decode(client_id_raw, validate=True)
                    if len(decoded) != 3:
                        raise ValueError("Cloudflare did not return a valid client ID")
                    reserved = list(decoded)

                    # Peer info
                    peers = config.get("peers", [])
                    if not isinstance(peers, list) or not peers:
                        raise ValueError("Cloudflare did not return a peer")
                    peer_pub = peers[0].get("public_key", "")
                    if len(base64.b64decode(peer_pub, validate=True)) != 32:
                        raise ValueError("Invalid Cloudflare peer key")
                    resolved_endpoint = peer_endpoint
                    if peers and isinstance(peers, list):
                        p = peers[0]
                        if p.get("public_key"):
                            peer_pub = p["public_key"]
                        if p.get("endpoint", {}).get("host"):
                            resolved_endpoint = p["endpoint"]["host"]

                    return {
                        "ok": True,
                        "warp_enabled": True,
                        "warp_private_key": private_key,
                        "warp_public_key": peer_pub,
                        "warp_endpoint": resolved_endpoint,
                        "warp_addresses": addresses,
                        "warp_reserved": reserved,
                        "account_id": data.get("id"),
                        "token": data.get("token"),
                        "message": "حساب جدید WARP با موفقیت ثبت شد.",
                    }
                else:
                    last_error = f"Cloudflare API returned status {resp.status_code}: {resp.text[:100]}"
        except httpx.ConnectError as exc:
            last_error = str(exc)
            logger.warning("Cloudflare registration connect error: %s", exc)
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Cloudflare registration attempt on %s failed: %s", endpoint, exc)

    # A locally generated key is unusable until Cloudflare registers its public
    # key. Keep the legacy argument for callers, but never report fake success.
    return {
        "ok": False,
        "message": f"ثبت حساب WARP در کلودفلر ناموفق بود: {last_error}",
    }
