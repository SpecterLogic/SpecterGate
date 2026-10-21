import pytest
from app.database import SessionLocal
from app.services.notifications import get_notification_config, send_smtp_email, send_discord_webhook, dispatch_notification
from app.services.settings import set_setting
from app.services.vault import put_secret


def test_notification_config_get_and_put(client, auth):
    # GET notifications
    resp = client.get("/api/integrations/notifications", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "smtp_enabled" in data
    assert "discord_enabled" in data

    # PUT notifications
    payload = {
        "smtp_enabled": True,
        "smtp_host": "smtp.mailgun.org",
        "smtp_port": 587,
        "smtp_username": "postmaster@example.com",
        "smtp_password": "secretpassword",
        "smtp_sender": "SpecterGate <alerts@example.com>",
        "smtp_recipient": "admin@example.com",
        "smtp_use_tls": True,
        "discord_enabled": True,
        "discord_webhook_url": "https://discord.com/api/webhooks/123/xyz",
    }
    update_resp = client.put("/api/integrations/notifications", json=payload, headers=auth)
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["smtp_enabled"] is True
    assert updated["smtp_host"] == "smtp.mailgun.org"
    assert updated["smtp_password_configured"] is True
    assert updated["discord_enabled"] is True
    assert updated["discord_webhook_configured"] is True


def test_send_smtp_email_mocked(monkeypatch):
    sent_messages = []

    class MockSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, msg):
            sent_messages.append(msg)

    monkeypatch.setattr("smtplib.SMTP", MockSMTP)

    with SessionLocal() as db:
        set_setting(db, "smtp_host", "smtp.test.com")
        set_setting(db, "smtp_recipient", "admin@test.com")
        set_setting(db, "smtp_sender", "alerts@test.com")
        put_secret(db, "smtp_password", "pw123")
        db.commit()

        ok, msg = send_smtp_email(db, "Subject Test", "Body Test")
        assert ok is True
        assert len(sent_messages) == 1
        assert sent_messages[0]["Subject"] == "Subject Test"


def test_send_discord_webhook_mocked(monkeypatch):
    class MockResponse:
        status_code = 204
        text = ""

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json=None, **kwargs):
            assert "embeds" in json
            return MockResponse()

    monkeypatch.setattr("httpx.Client", MockClient)

    with SessionLocal() as db:
        put_secret(db, "discord_webhook_url", "https://discord.com/api/webhooks/test")
        db.commit()

        ok, msg = send_discord_webhook(db, "Alert Title", "Alert Description")
        assert ok is True


def test_dispatch_notification(monkeypatch):
    class MockResponse:
        status_code = 204
        text = ""

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", MockClient)

    with SessionLocal() as db:
        set_setting(db, "smtp_enabled", False)
        set_setting(db, "discord_enabled", True)
        put_secret(db, "discord_webhook_url", "https://discord.com/api/webhooks/test")
        db.commit()

        res = dispatch_notification(db, "Quota Warning", "User exceeded 90% bandwidth", severity="warning")
        assert "discord" in res
        assert res["discord"]["ok"] is True
