import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).resolve().parent / "test_spectergate.db"
TEST_DB.unlink(missing_ok=True)

os.environ["SPECTERGATE_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SPECTERGATE_ADMIN_USERNAME"] = "admin"
os.environ["SPECTERGATE_ADMIN_PASSWORD"] = "test-admin-123"
os.environ["SPECTERGATE_DEMO_DATA"] = "false"
os.environ["SPECTERGATE_SECRET_KEY"] = "test-secret-key-that-is-long-enough"
os.environ["SPECTERGATE_XRAY_BINARY"] = "definitely-not-installed-xray"
os.environ["SPECTERGATE_PUBLIC_HOST"] = "panel.test"
os.environ["SPECTERGATE_TRUSTED_HOSTS"] = "testserver,panel.test,localhost,127.0.0.1"

os.environ["SPECTERGATE_SESSION_COOKIE_SECURE"] = "false"

from app.main import app  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    from app.services import telegram_bot
    async def idle(stop):
        await stop.wait()
    monkeypatch.setattr(telegram_bot, "run", idle)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def sample_user(client, auth):
    response = client.post(
        "/api/users",
        headers=auth,
        json={
            "username": f"test_user_{uuid.uuid4().hex[:6]}",
            "email": "test@example.com",
            "data_limit_bytes": 10 * 1024**3,
            "device_limit": 2,
            "expire_at": "2030-01-01T00:00:00Z",
            "note": "pytest user",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
