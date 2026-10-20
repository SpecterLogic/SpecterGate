import uuid

import pytest

from app.config import Settings
from app.database import SessionLocal
from app.models import VPNUser


def name(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def make_admin(client, auth, **extra):
    payload = {"username": name("dealer"), "password": "secure-dealer-123", "role": "reseller", "scope": "own", **extra}
    result = client.post("/api/admins", headers=auth, json=payload)
    assert result.status_code == 201, result.text
    login = client.post("/api/auth/login", json={"username": payload["username"], "password": payload["password"]})
    return result.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_reject_placeholder_secrets():
    with pytest.raises(ValueError):
        Settings(secret_key="replace-with-a-long-random-secret", admin_password="a-long-password-123")
    with pytest.raises(ValueError):
        Settings(secret_key="a" * 64, admin_password="admin123")


def test_browser_cookie_csrf_logout(client):
    result = client.post("/api/auth/session", headers={"Origin": "http://localhost:5173"}, json={"username": "admin", "password": "test-admin-123"})
    assert result.status_code == 200, result.text
    assert "access_token" not in result.json()
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=strict" in result.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_password_change_revokes_prior_tokens(client, auth):
    dealer, token = make_admin(client, auth)
    changed = client.post("/api/auth/change-password", headers=token, json={"current_password": "secure-dealer-123", "new_password": "a-new-password-123"})
    assert changed.status_code == 200
    assert client.get("/api/auth/me", headers=token).status_code == 401


def test_reset_password_revokes_prior_tokens(client, auth):
    dealer, token = make_admin(client, auth)
    assert client.patch(f"/api/admins/{dealer['id']}", headers=auth, json={"password": "replacement-123"}).status_code == 200
    assert client.get("/api/auth/me", headers=token).status_code == 401


def test_delegation_scope_and_cycle(client, auth):
    parent, parent_auth = make_admin(client, auth, permissions=["admins.manage", "admins.read", "users.read"])
    other, _ = make_admin(client, auth)
    assert client.get(f"/api/admins/{other['id']}", headers=parent_auth).status_code == 403
    assert client.patch(f"/api/admins/{parent['id']}", headers=parent_auth, json={"scope": "all"}).status_code == 403
    child = client.post("/api/admins", headers=parent_auth, json={"username": name("child"), "password": "secure-child-123", "role": "support", "permissions": ["users.read"], "scope": "own"})
    assert child.status_code == 201, child.text
    assert child.json()["parent_id"] == parent["id"]
    assert client.patch(f"/api/admins/{parent['id']}", headers=auth, json={"parent_id": child.json()["id"]}).status_code == 400
    assert client.post("/api/admins", headers=parent_auth, json={"username": name("bad"), "password": "secure-child-123", "permissions": ["settings.manage"]}).status_code == 403


def test_group_shared_quota_applies_to_clients_and_filter(client, auth, sample_user):
    group = client.post("/api/subscriptions", headers=auth, json={"name": name("family"), "max_members": 1, "data_limit_bytes": 100}).json()
    result = client.post(f"/api/subscriptions/{group['id']}/members", headers=auth, json={"user_ids": [sample_user["id"]]})
    assert result.status_code == 200
    with SessionLocal() as db:
        db.get(VPNUser, sample_user["id"]).download_bytes = 100
        db.commit()
    user = client.get(f"/api/users/{sample_user['id']}", headers=auth).json()
    assert user["status"] == "limited"
    import base64
    response = client.get(f"/sub/{sample_user['sub_token']}")
    assert response.status_code == 200
    assert "127.0.0.1:9" in base64.b64decode(response.text).decode()
    assert sample_user["uuid"] not in base64.b64decode(response.text).decode()
    filtered = client.get("/api/users", headers=auth, params={"status": "limited", "search": sample_user["username"]})
    assert filtered.json()["total"] == 1
    preview = client.get("/api/xray/config", headers=auth).json()["config"]
    clients = [c for i in preview["inbounds"] for c in i.get("settings", {}).get("clients", [])]
    assert not any(c.get("email") == sample_user["uuid"] for c in clients)
    rotated = client.post(f"/api/subscriptions/{group['id']}/rotate-token", headers=auth)
    assert rotated.status_code == 200
    assert client.get(f"/sub/{group['token']}/info").status_code == 404


def test_template_cannot_override_plan_and_renew_is_charged(client, auth):
    plan = client.post("/api/plans", headers=auth, json={"name": name("plan"), "price": 10, "days": 7, "data_limit_bytes": 1000}).json()
    dealer, token = make_admin(client, auth, credit=30, require_template=True)
    result = client.post("/api/users", headers=token, json={"username": name("buyer"), "plan_id": plan["id"], "data_limit_bytes": None, "expire_at": None})
    assert result.status_code == 201, result.text
    user = result.json()
    assert user["data_limit_bytes"] == 1000
    assert user["expire_at"] is not None
    assert client.patch(f"/api/users/{user['id']}", headers=token, json={"data_limit_bytes": None}).status_code == 403
    assert client.post("/api/subscriptions", headers=token, json={"name": name("family")}).status_code == 400
    renewed = client.post(f"/api/users/{user['id']}/renew", headers=token, json={"plan_id": plan["id"]})
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["uuid"] == user["uuid"]
    assert renewed.json()["expire_at"] > user["expire_at"]
    assert client.get("/api/auth/me", headers=token).json()["credit"] == 10


def test_bulk_scope_is_atomic(client, auth, sample_user):
    _, token = make_admin(client, auth)
    mine = client.post("/api/users", headers=token, json={"username": name("mine")}).json()
    result = client.post("/api/users/bulk", headers=token, json={"user_ids": [mine["id"], sample_user["id"]], "action": "disable"})
    assert result.status_code == 403
    assert client.get(f"/api/users/{mine['id']}", headers=token).json()["is_active"]


def test_login_throttles_failures(client):
    username = name("missing")
    for _ in range(10):
        assert client.post("/api/auth/login", json={"username": username, "password": "wrong-password"}).status_code == 401
    result = client.post("/api/auth/login", json={"username": username, "password": "wrong-password"})
    assert result.status_code == 429
    assert int(result.headers["retry-after"]) > 0


def test_invalid_xray_config_preserves_active_file(monkeypatch, tmp_path):
    from app.services import xray
    path = tmp_path / "active.json"
    path.write_text('{"old": true}')
    monkeypatch.setattr(xray.settings, "xray_config_path", str(path))
    monkeypatch.setattr(xray, "generate_config", lambda db: ({"new": True}, [], [], 0))
    monkeypatch.setattr(xray, "validate_config", lambda path: (False, "bad config"))
    assert xray.apply_config(None)["ok"] is False
    assert path.read_text() == '{"old": true}'
