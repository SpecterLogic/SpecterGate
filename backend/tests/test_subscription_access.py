import base64
import importlib.util
import time
import uuid
from pathlib import Path

from app.database import SessionLocal
from app.models import VPNUser, WireGuardPeer
from app.services import wireguard


def test_custom_subscription_browser_redirect_and_client_headers(client, auth):
    slug = "custom_" + uuid.uuid4().hex[:10]
    response = client.post("/api/users", headers=auth, json={"username": slug, "subscription_slug": slug, "expire_at": "2030-01-01T00:00:00Z", "data_limit_bytes": 1024**3})
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["sub_token"] == slug
    page = client.get(f"/sub/{slug}", headers={"Accept": "text/html"}, follow_redirects=False)
    assert page.status_code == 302
    assert page.headers["location"].endswith(f"/s/{slug}")
    client.put("/api/settings", headers=auth, json={"announcement": "پیام مدیر: سرویس فعال است"})
    response = client.get(f"/sub/{slug}", headers={"User-Agent": "Happ/1.0", "Accept": "*/*"})
    assert response.status_code == 200
    assert "total=1073741824" in response.headers["subscription-userinfo"]
    assert response.headers["profile-web-page-url"].endswith(f"/s/{slug}")
    assert base64.b64decode(response.headers["announce"].removeprefix("base64:")).decode() == "پیام مدیر: سرویس فعال است"
    exported = client.get(f"/sub/{slug}?format=raw", headers={"Accept": "text/html"}, follow_redirects=False)
    assert exported.status_code == 200
    duplicate = client.post("/api/users", headers=auth, json={"username": "other_" + uuid.uuid4().hex[:8], "subscription_slug": slug})
    assert duplicate.status_code == 409
    invalid = client.patch(f"/api/users/{user['id']}", headers=auth, json={"subscription_slug": "../bad"})
    assert invalid.status_code == 422
    changed = client.patch(f"/api/users/{user['id']}", headers=auth, json={"subscription_slug": slug + "_new"})
    assert changed.status_code == 200
    assert client.get(f"/sub/{slug}/info").status_code == 404
    client.put("/api/settings", headers=auth, json={"announcement": ""})


def test_wireguard_encrypted_config_metering_and_expiry(client, auth, sample_user, monkeypatch, tmp_path):
    server_key = base64.b64encode(bytes(range(32))).decode()
    state = {"ready": True, "epoch": "boot:1", "public_key": server_key, "peers": {}}
    monkeypatch.setattr(wireguard, "server_status", lambda: state)
    monkeypatch.setattr(wireguard, "MANIFEST", tmp_path / "desired.json")
    response = client.post(f"/api/wireguard/users/{sample_user['id']}", headers=auth, json={"endpoint_host": "203.0.113.10"})
    assert response.status_code == 200, response.text
    assert "Endpoint = 203.0.113.10:51820" in response.json()["config"]
    assert "AllowedIPs = 0.0.0.0/0" in response.json()["config"]
    with SessionLocal() as db:
        peer = db.query(WireGuardPeer).filter_by(user_id=sample_user["id"]).one()
        state["peers"] = {peer.public_key: {"rx": 400, "tx": 800}}
        wireguard.reconcile(db)
        wireguard.reconcile(db)
        user = db.get(VPNUser, sample_user["id"])
        assert (user.upload_bytes, user.download_bytes) == (400, 800)
        user.data_limit_bytes = 1000
        db.commit()
        wireguard.reconcile(db)
        assert peer.public_key not in (tmp_path / "desired.json").read_text()
    denied = client.get(f"/sub/{sample_user['sub_token']}?format=wireguard")
    assert denied.status_code == 409


def test_privileged_wireguard_manifest_validation():
    source = Path(__file__).resolve().parents[2] / "deploy" / "wireguard_agent.py"
    spec = importlib.util.spec_from_file_location("wg_agent", source)
    agent = importlib.util.module_from_spec(spec)
    # grp is Unix-only; validate via AST-extracted function on every platform.
    import ast
    import ipaddress
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "validated_peers")
    namespace = {"time": time, "base64": base64, "ipaddress": ipaddress}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    validate = namespace["validated_peers"]
    key = base64.b64encode(bytes(range(32))).decode()
    assert validate({"updated_at": time.time(), "peers": [{"public_key": key, "address": "10.88.0.2"}]}) == [(key, "10.88.0.2")]
    assert validate({"updated_at": 1, "peers": []}) == []
    import pytest
    for row in [{"public_key": key, "address": "127.0.0.1"}, {"public_key": key + "\nPostUp=bad", "address": "10.88.0.2"}]:
        with pytest.raises(ValueError):
            validate({"updated_at": time.time(), "peers": [row]})
