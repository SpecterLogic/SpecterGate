"""Native WireGuard provisioning; the web process never receives CAP_NET_ADMIN."""
import base64
import ipaddress
import json
import os
import time
import threading
from functools import wraps
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from sqlalchemy.orm import Session
from sqlalchemy import update

from app.config import BASE_DIR, settings
from app.models import WireGuardPeer, VPNUser
from app.services import vault

MANIFEST = BASE_DIR / "data" / "wireguard" / "desired.json"
STATUS = Path("/run/spectergate-wg/status.json")
LOCK = threading.RLock()


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with LOCK:
            return function(*args, **kwargs)
    return wrapped


def server_status():
    try:
        data = json.loads(STATUS.read_text())
        if time.time() - float(data["updated_at"]) > 90:
            return {"ready": False}
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {"ready": False}


def provision(db: Session, user: VPNUser) -> WireGuardPeer:
    peer = db.query(WireGuardPeer).filter_by(user_id=user.id).first()
    if peer:
        peer.is_active = True
        return peer
    used = {p.address for p in db.query(WireGuardPeer).all()}
    address = next((str(ipaddress.ip_address(int(ipaddress.ip_address("10.88.0.2")) + n)) for n in range(65532)
                    if str(ipaddress.ip_address(int(ipaddress.ip_address("10.88.0.2")) + n)) not in used), None)
    if not address:
        raise ValueError("WireGuard address pool is full.")
    key = X25519PrivateKey.generate()
    private = base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    peer = WireGuardPeer(user_id=user.id, public_key=public, address=address)
    db.add(peer)
    db.flush()
    vault.put_secret(db, f"wireguard_peer_{peer.id}", private)
    return peer


def client_config(db: Session, peer: WireGuardPeer, endpoint: str | None = None) -> str:
    server = server_status()
    if not server.get("ready"):
        raise ValueError("Native WireGuard service is not ready; install deploy/wireguard_install.sh first.")
    user = db.get(VPNUser, peer.user_id)
    if not peer.is_active or user is None or user.status != "active":
        raise ValueError("WireGuard access is inactive.")
    private = vault.get_secret(db, f"wireguard_peer_{peer.id}")
    if not private:
        raise ValueError("Restore the WireGuard peer encryption key from backup.")
    host = endpoint or settings.public_host
    if ":" in host:
        host = f"[{host}]"
    return (f"[Interface]\nPrivateKey = {private}\nAddress = {peer.address}/32\nDNS = 1.1.1.1, 1.0.0.1\nMTU = 1280\n\n"
            f"[Peer]\nPublicKey = {server['public_key']}\nAllowedIPs = 0.0.0.0/0\nEndpoint = {host}:{int(server.get('port', 51820))}\nPersistentKeepalive = 25\n")


@serialized
def reconcile(db: Session):
    server = server_status()
    stats = server.get("peers", {}) if server.get("ready") else {}
    peers = db.query(WireGuardPeer).all()
    desired = []
    for peer in peers:
        user = db.get(VPNUser, peer.user_id)
        sample = stats.get(peer.public_key)
        if sample is not None and user is not None:
            rx, tx = max(0, int(sample["rx"])), max(0, int(sample["tx"]))
            same_epoch = peer.counter_epoch == server.get("epoch", "")
            upload = max(0, rx - peer.last_rx) if same_epoch and rx >= peer.last_rx else rx
            download = max(0, tx - peer.last_tx) if same_epoch and tx >= peer.last_tx else tx
            db.execute(update(VPNUser).where(VPNUser.id == user.id).values(
                upload_bytes=VPNUser.upload_bytes + upload,
                download_bytes=VPNUser.download_bytes + download,
            ))
            db.refresh(user)
            peer.last_rx, peer.last_tx = rx, tx
            peer.counter_epoch = server.get("epoch", "")
        if peer.is_active and user is not None and user.status == "active":
            desired.append({"public_key": peer.public_key, "address": peer.address})
    db.commit()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temp = MANIFEST.with_suffix(".tmp")
    temp.write_text(json.dumps({"updated_at": time.time(), "peers": desired}), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(MANIFEST)
