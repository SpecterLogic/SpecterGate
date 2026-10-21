import pytest
from app.database import SessionLocal
from app.models import Inbound, VPNUser
from app.services.monitoring import (
    get_active_sessions,
    register_user_session,
    terminate_session,
    terminate_user_sessions,
)


def test_get_inbound_speeds(client, auth):
    # Ensure an inbound exists
    with SessionLocal() as db:
        inbound = db.query(Inbound).first()
        if not inbound:
            inbound = Inbound(
                tag="test-inbound-speed",
                remark="Speed Test",
                protocol="vless",
                network="tcp",
                port=20999,
                is_active=True,
            )
            db.add(inbound)
            db.commit()

    res = client.get("/api/monitoring/speeds", headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first = data[0]
    assert "upload_speed_bps" in first
    assert "download_speed_bps" in first


def test_register_and_list_sessions(client, auth, sample_user):
    user_id = sample_user["id"]
    with SessionLocal() as db:
        user = db.get(VPNUser, user_id)
        # Register session from IP 1.2.3.4
        sid1 = register_user_session(db, user, "1.2.3.4", "V2rayNG/1.8")
        assert sid1 is not None

    # List sessions via API
    res = client.get(f"/api/monitoring/sessions?user_id={user_id}", headers=auth)
    assert res.status_code == 200
    sessions = res.json()
    assert len(sessions) >= 1
    assert any(s["client_ip"] == "1.2.3.4" for s in sessions)


def test_device_limit_enforcement(client, auth, sample_user):
    user_id = sample_user["id"]
    with SessionLocal() as db:
        user = db.get(VPNUser, user_id)
        user.device_limit = 2
        db.commit()

        # Clean previous sessions for test
        terminate_user_sessions(user.id)

        # Connect 1st device
        register_user_session(db, user, "10.0.0.1", "Phone 1")
        # Connect 2nd device
        register_user_session(db, user, "10.0.0.2", "Laptop 2")

        # Re-registering existing device IP must succeed (refresh session)
        register_user_session(db, user, "10.0.0.1", "Phone 1")

        # 3rd device must exceed limit and raise 429
        with pytest.raises(Exception) as excinfo:
            register_user_session(db, user, "10.0.0.3", "Tablet 3")
        assert "429" in str(excinfo.value) or "تعداد دستگاه‌های مجاز" in str(excinfo.value)


def test_terminate_session_api(client, auth, sample_user, monkeypatch):
    monkeypatch.setattr("app.services.xray.xray_status", lambda: {"running": True})
    monkeypatch.setattr("app.services.session_control.available", lambda: True)
    monkeypatch.setattr("app.services.session_control.sync", lambda db: {"protocol_version": 1})
    monkeypatch.setattr("app.services.xray.apply_config", lambda db: pytest.fail("disconnect restarted core"))
    user_id = sample_user["id"]
    with SessionLocal() as db:
        user = db.get(VPNUser, user_id)
        sid = register_user_session(db, user, "192.168.99.1", "Client Terminate Test")

    # Terminate by ID
    term_res = client.post(f"/api/monitoring/sessions/{sid}/terminate", headers=auth)
    assert term_res.status_code == 200
    assert term_res.json()["ok"] is True

    # Terminate all for user
    term_all_res = client.post(f"/api/monitoring/users/{user_id}/terminate-sessions", headers=auth)
    assert term_all_res.status_code == 200
    assert term_all_res.json()["ok"] is True


def test_scoped_admin_cannot_read_or_terminate_other_sessions(client, auth, sample_user):
    import uuid
    username = "session_admin_" + uuid.uuid4().hex[:8]
    created = client.post("/api/admins", headers=auth, json={
        "username": username, "password": "scoped-password-123", "role": "reseller",
        "scope": "own", "permissions": ["users.read", "users.write"],
    })
    assert created.status_code == 201, created.text
    login = client.post("/api/auth/login", json={"username": username, "password": "scoped-password-123"})
    scoped = {"Authorization": "Bearer " + login.json()["access_token"]}
    with SessionLocal() as db:
        user = db.get(VPNUser, sample_user["id"])
        sid = register_user_session(db, user, "203.0.113.25")
    try:
        sessions = client.get("/api/monitoring/sessions", headers=scoped)
        assert sessions.status_code == 200
        assert all(item["session_id"] != sid for item in sessions.json())
        assert client.post(f"/api/monitoring/sessions/{sid}/terminate", headers=scoped).status_code == 403
        assert any(item["session_id"] == sid for item in get_active_sessions())
    finally:
        terminate_session(sid)


def test_legacy_core_refuses_disconnect_without_restart(client, auth, sample_user, monkeypatch):
    monkeypatch.setattr("app.services.xray.xray_status", lambda: {"running": True})
    monkeypatch.setattr("app.services.session_control.available", lambda: False)
    monkeypatch.setattr("app.services.xray.apply_config", lambda db: pytest.fail("legacy core restarted"))
    with SessionLocal() as db:
        user = db.get(VPNUser, sample_user["id"])
        sid = register_user_session(db, user, "192.0.2.91")
    try:
        result = client.post(f"/api/monitoring/sessions/{sid}/terminate", headers=auth)
        assert result.status_code == 503
        assert any(row["session_id"] == sid for row in get_active_sessions())
    finally:
        terminate_session(sid)


def test_ip_limit_and_temporary_blocks_do_not_change_core_config(sample_user):
    from app.services.xray import generate_config, config_hash
    from app.services.monitoring import block_session
    with SessionLocal() as db:
        user = db.get(VPNUser, sample_user["id"])
        before = config_hash(generate_config(db)[0])
        user.device_limit = 7
        db.commit()
        block_session(db, user, "192.0.2.90")
        assert config_hash(generate_config(db)[0]) == before
