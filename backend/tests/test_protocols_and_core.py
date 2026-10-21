import pytest
from app.services.external_protocols import (
    generate_hysteria2_client_uri,
    generate_hysteria2_outbound,
    generate_tuic_client_uri,
    generate_tuic_outbound,
    generate_shadowtls_outbound,
    generate_mtproto_fake_tls_secret,
    generate_mtproto_link,
)
from app.services.inbound_options import AdvancedInbound, TLSOptions, RealityOptions, XHTTPOptions, apply_stream_options


def test_external_protocols_generators():
    # 1. Hysteria 2
    hy2_uri = generate_hysteria2_client_uri(
        server="198.51.100.1",
        port=8443,
        password="test-password-123",
        sni="www.bing.com",
        obfs_password="obfs-secret",
    )
    assert hy2_uri.startswith("hysteria2://test-password-123@198.51.100.1:8443/")
    assert "sni=www.bing.com" in hy2_uri
    assert "obfs=salamander" in hy2_uri

    hy2_out = generate_hysteria2_outbound(
        server="198.51.100.1",
        port=8443,
        password="test-password-123",
        sni="www.bing.com",
        obfs_password="obfs-secret",
    )
    assert hy2_out["type"] == "hysteria2"
    assert hy2_out["server"] == "198.51.100.1"
    assert hy2_out["obfs"]["type"] == "salamander"

    # 2. TUIC
    tuic_uri = generate_tuic_client_uri(
        server="198.51.100.2",
        port=8443,
        uuid_str="c731e84d-2a1c-4b68-8092-23c21a478b8a",
        password="tuic-secret-password",
        congestion_control="bbr",
    )
    assert tuic_uri.startswith("tuic://c731e84d-2a1c-4b68-8092-23c21a478b8a:tuic-secret-password@198.51.100.2:8443/")
    assert "congestion_control=bbr" in tuic_uri

    tuic_out = generate_tuic_outbound(
        server="198.51.100.2",
        port=8443,
        uuid_str="c731e84d-2a1c-4b68-8092-23c21a478b8a",
        password="tuic-secret-password",
    )
    assert tuic_out["type"] == "tuic"
    assert tuic_out["tls"]["alpn"] == ["h3"]

    # 3. ShadowTLS
    stls = generate_shadowtls_outbound(
        server="198.51.100.3",
        port=443,
        password="shadow-password",
        sni="gateway.icloud.com",
    )
    assert stls["type"] == "shadowtls"
    assert stls["version"] == 3

    # 4. Telegram MTProto Fake-TLS
    secret = generate_mtproto_fake_tls_secret("www.cloudflare.com")
    assert secret.startswith("ee")
    assert len(secret) > 34
    tg_link = generate_mtproto_link("198.51.100.4", 443, secret)
    assert tg_link.startswith("https://t.me/proxy?server=198.51.100.4&port=443&secret=ee")


def test_core_options_ech_mldsa65_finalmask_xdrive():
    # Test AdvancedInbound validation
    adv = AdvancedInbound(
        tls=TLSOptions(ech=True, echConfig="test-ech-config", mldsa65=True),
        reality=RealityOptions(finalMask=True, finalMaskConfig="test-mask-config"),
        xhttp=XHTTPOptions(mode="x-drive", xdrive=True),
    )
    assert adv.tls.ech is True
    assert adv.tls.mldsa65 is True
    assert adv.reality.finalMask is True
    assert adv.xhttp.mode == "x-drive"

    # Test apply_stream_options
    class MockInbound:
        network = "tcp"
        security = "tls"
        extra_json = adv.model_dump_json()

    stream = {}
    apply_stream_options(MockInbound(), stream)
    assert "tlsSettings" in stream
    assert stream["tlsSettings"].get("enableECH") is True
    assert stream["tlsSettings"].get("echConfig") == "test-ech-config"
    assert "X25519MLKEM768" in stream["tlsSettings"].get("curvePreferences", [])


def test_protocols_and_xray_api(client, auth, monkeypatch):
    from app.services import xray as xray_service
    monkeypatch.setattr(xray_service, "apply_config", lambda db: {"ok": True})

    # 1. Protocols Overview
    overview_resp = client.get("/api/protocols/overview", headers=auth)
    assert overview_resp.status_code == 200
    data = overview_resp.json()
    assert len(data["native_protocols"]) >= 5
    assert len(data["extended_families"]) >= 4

    # 2. Hysteria 2 API
    hy2_resp = client.post(
        "/api/protocols/hysteria2/generate",
        json={
            "server": "example.com",
            "port": 443,
            "password": "secretpassword",
            "sni": "www.bing.com",
        },
        headers=auth,
    )
    assert hy2_resp.status_code == 200
    assert "uri" in hy2_resp.json()

    # 3. Telegram Secret API
    tg_sec_resp = client.post(
        "/api/protocols/telegram/secret",
        json={"domain": "www.google.com"},
        headers=auth,
    )
    assert tg_sec_resp.status_code == 200
    assert tg_sec_resp.json()["secret"].startswith("ee")

    # 4. Xray Versions API
    ver_resp = client.get("/api/xray/versions", headers=auth)
    assert ver_resp.status_code == 200
    ver_data = ver_resp.json()
    assert "current_version" in ver_data
    assert "available_channels" in ver_data

    # 5. Xray Restart All API
    restart_resp = client.post("/api/xray/service/restart-all", headers=auth)
    assert restart_resp.status_code == 200
    assert restart_resp.json()["ok"] is True
