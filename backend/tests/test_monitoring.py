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


def test_terminate_session_api(client, auth, sample_user):
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
