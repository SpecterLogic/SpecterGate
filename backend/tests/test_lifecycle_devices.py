from datetime import datetime, timedelta, timezone
from app.database import SessionLocal
from app.models import VPNUser, UserDevice, as_utc
from app.services.user_lifecycle import reconcile


def test_hwid_all_formats_and_info_cannot_bypass(client, auth, sample_user):
    created = client.post("/api/inbounds", headers=auth, json={"tag": "hwid-inbound", "remark": "HWID test", "port": 24001, "protocol": "vless", "network": "tcp", "security": "none"})
    assert created.status_code == 201, created.text
    path = f"/sub/{sample_user['sub_token']}"
    assert client.patch(f"/api/users/{sample_user['id']}", headers=auth, json={"hwid_limit": 1}).status_code == 200
    assert client.get(path + "?format=raw").status_code == 403
    first = {"x-hwid": "first-device-identifier"}
    assert client.get(path + "?format=raw", headers=first).status_code == 200
    assert client.get(path + "?format=singbox", headers=first).status_code == 200
    assert client.get(path + "?format=json", headers={"x-hwid": "second-device-identifier"}).status_code == 403
    assert client.get(path + "/info").json()["links"] == []
    devices = client.get(f"/api/users/{sample_user['id']}/devices", headers=auth).json()
    assert len(devices) == 1 and "fingerprint" not in devices[0]
    assert client.delete(f"/api/users/{sample_user['id']}/devices/{devices[0]['id']}", headers=auth).status_code == 200
    assert client.get(path, headers={"x-hwid": "second-device-identifier"}).status_code == 200


def test_cycles_catch_up_once_and_bounded_renewal(client, sample_user):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user = db.get(VPNUser, sample_user["id"])
        user.upload_bytes, user.download_bytes = 20, 40
        user.traffic_reset_days = 7
        user.traffic_reset_at = now - timedelta(days=16)
        db.commit()
        reconcile(db, now)
        assert user.used_traffic_bytes == 0
        assert as_utc(user.traffic_reset_at) == now - timedelta(days=2)
        user.upload_bytes = 9
        db.commit()
        reconcile(db, now)
        assert user.upload_bytes == 9
        user.expire_at = now - timedelta(days=1)
        user.renewal_days, user.renewal_remaining = 30, 1
        db.commit()
        reconcile(db, now)
        assert user.renewal_remaining == 0
        assert as_utc(user.expire_at) == now + timedelta(days=30)
        reconcile(db, now + timedelta(days=31))
        assert as_utc(user.expire_at) == now + timedelta(days=30)
