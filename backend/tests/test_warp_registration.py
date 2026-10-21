import pytest
from app.services.warp_client import generate_wireguard_keypair, register_warp_account


def test_generate_wireguard_keypair():
    priv, pub = generate_wireguard_keypair()
    assert isinstance(priv, str) and len(priv) == 44
    assert isinstance(pub, str) and len(pub) == 44
    assert priv != pub


def test_register_warp_account_fallback(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("Registration unavailable")
    monkeypatch.setattr("httpx.Client", unavailable)
    result = register_warp_account(allow_fallback=True, timeout_seconds=1.0)
    assert result["ok"] is False
    assert "warp_private_key" not in result


def test_register_warp_mocked_success(monkeypatch):
    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "id": "cf-acc-12345",
                "token": "secret-token",
                "config": {
                    "client_id": "AAAA",  # base64 for 3 zero bytes
                    "peers": [
                        {
                            "public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
                            "endpoint": {"host": "engage.cloudflareclient.com:2408"},
                        }
                    ],
                    "interface": {
                        "addresses": {
                            "v4": "172.16.0.2/32",
                            "v6": "2606:4700:110:8f6b:1234:5678:9abc:def0/128",
                        }
                    },
                },
            }

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

    result = register_warp_account()
    assert result["ok"] is True
    assert result["account_id"] == "cf-acc-12345"
    assert result["warp_addresses"] == [
        "172.16.0.2/32",
        "2606:4700:110:8f6b:1234:5678:9abc:def0/128",
    ]
    assert result["warp_reserved"] == [0, 0, 0]


def test_warp_auto_register_endpoint(client, auth, monkeypatch):
    monkeypatch.setattr("app.routers.routing.register_warp_account", lambda **kwargs: {"ok": False, "message": "Registration unavailable"})
    resp = client.post("/api/routing/warp/auto-register?allow_fallback=true", headers=auth)
    assert resp.status_code == 502


def test_incomplete_success_response_is_not_a_registered_account(monkeypatch):
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs):
            return type("Response", (), {"status_code": 200, "json": lambda self: {"id": "id", "token": "token", "config": {}}})()
    monkeypatch.setattr("httpx.Client", Client)
    result = register_warp_account(allow_fallback=True)
    assert result["ok"] is False
    assert "warp_private_key" not in result
