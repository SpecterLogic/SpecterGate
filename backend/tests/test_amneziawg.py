import json
import pytest
from app.database import SessionLocal
from app.models import VPNUser
from app.services.amneziawg import get_amnezia_params, save_amnezia_params, randomize_params


def test_get_and_update_amnezia_params(client, auth):
    res = client.get("/api/amneziawg/params", headers=auth)
    assert res.status_code == 200
    params = res.json()
    assert "jc" in params
    assert "h1" in params
    assert "port" in params

    # Update parameters
    update_payload = {
        "enabled": True,
        "port": 51821,
        "server_address": "10.89.0.1/24",
        "jc": 5,
        "jmin": 60,
        "jmax": 900,
        "s1": 45,
        "s2": 45,
        "h1": 222333444,
        "h2": 555666777,
        "h3": 888999111,
        "h4": 111222333,
    }
    put_res = client.put("/api/amneziawg/params", json=update_payload, headers=auth)
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["port"] == 51821
    assert updated["jc"] == 5
    assert updated["h1"] == 222333444


def test_randomize_amnezia_params(client, auth):
    post_res = client.post("/api/amneziawg/randomize", headers=auth)
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["h1"] > 0
    assert data["h2"] > 0
    assert data["h3"] > 0
    assert data["h4"] > 0
    # All 4 magic headers must be distinct
    assert len({data["h1"], data["h2"], data["h3"], data["h4"]}) == 4


def test_client_awg_config_and_vpn_uri(client, auth, sample_user):
    user_id = sample_user["id"]
    # Download client .conf
    conf_res = client.get(f"/api/amneziawg/client/{user_id}/config", headers=auth)
    assert conf_res.status_code == 200, conf_res.text
    text = conf_res.text
    assert "[Interface]" in text
    assert "[Peer]" in text
    assert "Jc =" in text
    assert "H1 =" in text
    assert "H4 =" in text

    # Get client vpn:// URI
    vpn_res = client.get(f"/api/amneziawg/client/{user_id}/vpn", headers=auth)
    assert vpn_res.status_code == 200
    vpn_data = vpn_res.json()
    assert vpn_data["uri"].startswith("vpn://")


def test_server_awg_config(client, auth, sample_user):
    user_id = sample_user["id"]
    # Ensure peer is provisioned for this user
    client.get(f"/api/amneziawg/client/{user_id}/config", headers=auth)

    res = client.get("/api/amneziawg/server-config", headers=auth)
    assert res.status_code == 200
    text = res.text
    assert "[Interface]" in text
    assert "ListenPort =" in text
    assert "H1 =" in text
    assert "[Peer]" in text
    assert sample_user["username"] in text


def test_subscription_export_amneziawg(client, auth, sample_user):
    token = sample_user["sub_token"]
    # Check info endpoint exposes amneziawg formats
    info_res = client.get(f"/sub/{token}/info")
    assert info_res.status_code == 200
    info_data = info_res.json()
    assert "amneziawg" in info_data["format_urls"]
    assert "amnezia_vpn" in info_data["format_urls"]

    # Check direct subscription download of format=amneziawg
    sub_res = client.get(f"/sub/{token}?format=amneziawg")
    assert sub_res.status_code == 200, sub_res.text
    assert "[Interface]" in sub_res.text
    assert "H1 =" in sub_res.text

    # Check format=amnezia_vpn
    vpn_res = client.get(f"/sub/{token}?format=amnezia_vpn")
    assert vpn_res.status_code == 200
    assert vpn_res.text.startswith("vpn://")
