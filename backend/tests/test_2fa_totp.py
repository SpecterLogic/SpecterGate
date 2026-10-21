import json
from app.database import SessionLocal
from app.models import Admin
from app.services.totp import generate_totp_secret, get_totp_token, verify_totp, create_2fa_setup
from app.services import login_guard


def test_totp_service_functions():
    secret = generate_totp_secret()
    assert len(secret) == 32
    token = get_totp_token(secret)
    assert len(token) == 6
    assert token.isdigit()
    assert verify_totp(secret, token) is True
    assert verify_totp(secret, "000000" if token != "000000" else "111111") is False

    setup = create_2fa_setup("testadmin")
    assert "secret" in setup
    assert "uri" in setup
    assert "qr_svg" in setup
    assert len(setup["recovery_codes"]) == 8


def test_2fa_api_flow(client, auth):
    # Clear any rate limit failures before starting
    with login_guard._lock:
        login_guard._failures.clear()

    # 1. Setup 2FA
    resp = client.post("/api/auth/2fa/setup", headers=auth)
    assert resp.status_code == 200
    setup_data = resp.json()
    secret = setup_data["secret"]
    recovery_codes = setup_data["recovery_codes"]
    assert len(recovery_codes) == 8

    # 2. Try enabling with wrong code -> 400
    resp = client.post(
        "/api/auth/2fa/enable",
        json={"secret": secret, "code": "000000", "recovery_codes": recovery_codes},
        headers=auth,
    )
    assert resp.status_code == 400

    # 3. Enable with valid code -> 200
    valid_code = get_totp_token(secret)
    resp = client.post(
        "/api/auth/2fa/enable",
        json={"secret": secret, "code": valid_code, "recovery_codes": recovery_codes},
        headers=auth,
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        assert admin.totp_enabled is True
        assert admin.totp_secret == secret
        assert admin.recovery_codes_json is not None

    # 4. Attempt login without OTP code -> 403 (2FA_REQUIRED)
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-123"})
    assert login_resp.status_code == 403
    assert login_resp.json()["detail"] == "2FA_REQUIRED"

    # 5. Login with wrong OTP -> 401
    bad_otp_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-123", "otp_code": "999999"},
    )
    assert bad_otp_resp.status_code == 401

    # 6. Login with recovery code -> 200
    first_code = recovery_codes[0]
    rec_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-123", "otp_code": first_code},
    )
    assert rec_resp.status_code == 200
    token = rec_resp.json()["access_token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # Verify recovery code was consumed
    with SessionLocal() as db:
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        remaining_codes = json.loads(admin.recovery_codes_json)
        assert first_code not in remaining_codes
        assert len(remaining_codes) == 7

    # 7. Disable 2FA
    disable_resp = client.post(
        "/api/auth/2fa/disable",
        json={"password": "test-admin-123"},
        headers=auth_header,
    )
    assert disable_resp.status_code == 200

    with SessionLocal() as db:
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        assert admin.totp_enabled is False
        assert admin.totp_secret is None

    # Clear rate limit failures after test so other tests are completely clean
    with login_guard._lock:
        login_guard._failures.clear()
