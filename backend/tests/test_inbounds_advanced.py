from datetime import datetime, timezone, timedelta
from app.models import Inbound, as_utc
from app.database import SessionLocal
from app.services.maintenance import reconcile_inbounds


def test_inbound_status_and_usage():
    now = datetime.now(timezone.utc)
    # Active inbound with no limits
    ib1 = Inbound(
        tag="ib-test-1",
        remark="Test 1",
        protocol="vless",
        port=1001,
        is_active=True,
        upload_bytes=1000,
        download_bytes=2000,
    )
    assert ib1.status == "active"
    assert ib1.usage_percent == 0.0
    assert ib1.is_usable is True

    # Inbound with data limit exceeded
    ib2 = Inbound(
        tag="ib-test-2",
        remark="Test 2",
        protocol="vless",
        port=1002,
        is_active=True,
        data_limit_bytes=5000,
        upload_bytes=3000,
        download_bytes=3000,
    )
    assert ib2.status == "limited"
    assert ib2.usage_percent == 100.0
    assert ib2.is_usable is False

    # Inbound expired
    ib3 = Inbound(
        tag="ib-test-3",
        remark="Test 3",
        protocol="vless",
        port=1003,
        is_active=True,
        expire_at=now - timedelta(days=1),
    )
    assert ib3.status == "expired"
    assert ib3.is_usable is False

    # Disabled inbound
    ib4 = Inbound(
        tag="ib-test-4",
        remark="Test 4",
        protocol="vless",
        port=1004,
        is_active=False,
    )
    assert ib4.status == "disabled"
    assert ib4.is_usable is False


def test_reconcile_inbounds_reset_interval(client):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=31)
    with SessionLocal() as db:
        ib = Inbound(
            tag="ib-reset-interval",
            remark="Reset Interval Test",
            protocol="vless",
            port=1005,
            is_active=True,
            upload_bytes=50000,
            download_bytes=50000,
            reset_interval_days=30,
            last_reset_at=past,
        )
        db.add(ib)
        db.commit()
        ib_id = ib.id

        reconcile_inbounds(db)
        db.expire_all()
        reloaded = db.get(Inbound, ib_id)

        assert reloaded.upload_bytes == 0
        assert reloaded.download_bytes == 0
        assert reloaded.last_reset_at is not None
        assert (now - as_utc(reloaded.last_reset_at)).total_seconds() < 10

        # cleanup
        db.delete(reloaded)
        db.commit()


def test_inbound_api_bulk_actions(client, auth):
    with SessionLocal() as db:
        ib1 = Inbound(tag="bulk-1", remark="Bulk 1", protocol="vless", port=1011, is_active=True, upload_bytes=100)
        ib2 = Inbound(tag="bulk-2", remark="Bulk 2", protocol="vless", port=1012, is_active=True, upload_bytes=200)
        ib3 = Inbound(tag="bulk-3", remark="Bulk 3", protocol="vless", port=1013, is_active=True, upload_bytes=300)
        db.add_all([ib1, ib2, ib3])
        db.commit()
        id1, id2, id3 = ib1.id, ib2.id, ib3.id

    # 1. Bulk Disable
    resp = client.post(
        "/api/inbounds/bulk/status",
        json={"inbound_ids": [id1, id2], "is_active": False},
        headers=auth,
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        assert db.get(Inbound, id1).is_active is False
        assert db.get(Inbound, id2).is_active is False
        assert db.get(Inbound, id3).is_active is True

    # 2. Bulk Reset Traffic
    resp = client.post(
        "/api/inbounds/bulk/reset-traffic",
        json={"inbound_ids": [id1, id2, id3]},
        headers=auth,
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        assert db.get(Inbound, id1).upload_bytes == 0
        assert db.get(Inbound, id2).upload_bytes == 0
        assert db.get(Inbound, id3).upload_bytes == 0
        assert db.get(Inbound, id1).last_reset_at is not None

    # 3. Single Inbound Reset Traffic
    with SessionLocal() as db:
        target = db.get(Inbound, id3)
        target.upload_bytes = 9999
        db.commit()

    resp = client.post(f"/api/inbounds/{id3}/reset-traffic", headers=auth)
    assert resp.status_code == 200
    with SessionLocal() as db:
        assert db.get(Inbound, id3).upload_bytes == 0

    # 4. Bulk Delete
    resp = client.post(
        "/api/inbounds/bulk/delete",
        json={"inbound_ids": [id1, id2]},
        headers=auth,
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        assert db.get(Inbound, id1) is None
        assert db.get(Inbound, id2) is None
        assert db.get(Inbound, id3) is not None
        # cleanup
        db.delete(db.get(Inbound, id3))
        db.commit()
