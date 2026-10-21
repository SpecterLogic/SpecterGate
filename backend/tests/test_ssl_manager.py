import pytest
from app.services.ssl_manager import generate_self_signed_cert


def test_upload_valid_certificate(client, auth):
    domain = "myvpn.example.com"
    cert_pem, key_pem = generate_self_signed_cert(domain)

    payload = {
        "domain": domain,
        "cert_pem": cert_pem,
        "key_pem": key_pem,
        "auto_renew": False,
    }
    res = client.post("/api/certificates/upload", json=payload, headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["domain"] == domain
    assert data["is_active"] is True
    assert data["days_remaining"] is not None and data["days_remaining"] > 0


def test_upload_mismatched_key_fails(client, auth):
    domain1 = "domain1.example.com"
    domain2 = "domain2.example.com"
    cert_pem, _ = generate_self_signed_cert(domain1)
    _, key_pem = generate_self_signed_cert(domain2)

    payload = {
        "domain": domain1,
        "cert_pem": cert_pem,
        "key_pem": key_pem,
    }
    res = client.post("/api/certificates/upload", json=payload, headers=auth)
    assert res.status_code == 400
    assert "همخوانی ندارد" in res.json()["detail"]


def test_issue_certificate(client, auth, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("Worker unavailable")
    monkeypatch.setattr("app.services.ssl_worker.issue", unavailable)
    domain = "auto.example.com"
    payload = {"domain": domain}
    res = client.post("/api/certificates/issue", json=payload, headers=auth)
    assert res.status_code == 503, res.text
    assert not any(item["domain"] == domain for item in client.get("/api/certificates", headers=auth).json())


@pytest.mark.parametrize("domain", ["..", "--help", "bad:domain", "bad name", "bad\nname", "-bad.example.com"])
def test_invalid_certificate_domains(client, auth, domain):
    response = client.post("/api/certificates/issue", headers=auth, json={"domain": domain})
    assert response.status_code == 400


def test_list_and_delete_certificate(client, auth):
    domain = "delete-me.example.com"
    cert_pem, key_pem = generate_self_signed_cert(domain)
    upload_res = client.post(
        "/api/certificates/upload",
        json={"domain": domain, "cert_pem": cert_pem, "key_pem": key_pem},
        headers=auth,
    )
    assert upload_res.status_code == 200
    cert_id = upload_res.json()["id"]

    # List
    list_res = client.get("/api/certificates", headers=auth)
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(c["id"] == cert_id for c in items)

    # Delete
    del_res = client.delete(f"/api/certificates/{cert_id}", headers=auth)
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True

    # Check removed from list
    list_res2 = client.get("/api/certificates", headers=auth)
    assert not any(c["id"] == cert_id for c in list_res2.json())
