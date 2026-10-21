from __future__ import annotations

import base64
import json


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_login_rejects_wrong_password(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert response.status_code == 401


def test_login_and_me(client, auth):
    response = client.get("/api/auth/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["username"] == "admin"
    assert response.json()["role"] == "superadmin"


def test_oauth2_form_token_flow(client):
    response = client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "test-admin-123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_user_crud_and_status(client, auth, sample_user):
    assert sample_user["status"] == "active"
    assert sample_user["subscription_path"].startswith("/sub/")

    listing = client.get("/api/users", headers=auth, params={"search": sample_user["username"]})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    updated = client.patch(
        f"/api/users/{sample_user['id']}",
        headers=auth,
        json={"note": "updated", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "disabled"

    reset = client.post(f"/api/users/{sample_user['id']}/reset-traffic", headers=auth)
    assert reset.status_code == 200
    assert reset.json()["used_traffic_bytes"] == 0

    deleted = client.delete(f"/api/users/{sample_user['id']}", headers=auth)
    assert deleted.status_code == 200


def test_dashboard_overview(client, auth):
    response = client.get("/api/dashboard/overview", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert "total_users" in data
    assert len(data["traffic_series"]) == 7


def test_inbound_reality_keys_and_config(client, auth):
    created = client.post(
        "/api/inbounds",
        headers=auth,
        json={
            "tag": "pytest-reality",
            "protocol": "vless",
            "port": 9443,
            "network": "tcp",
            "security": "reality",
            "remark": "Pytest Reality",
            "sni": "www.cloudflare.com",
            "reality_dest": "www.cloudflare.com:443",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    inbound = created.json()
    assert inbound["reality_public_key"]
    assert inbound["reality_private_key"]
    assert inbound["flow"] == "xtls-rprx-vision"

    preview = client.get("/api/xray/config", headers=auth)
    assert preview.status_code == 200
    payload = preview.json()
    tags = [item["tag"] for item in payload["config"]["inbounds"]]
    assert "pytest-reality" in tags
    assert payload["client_count"] >= 0

    deleted = client.delete(f"/api/inbounds/{inbound['id']}", headers=auth)
    assert deleted.status_code == 200


def test_subscription_payload(client, auth, sample_user):
    inbound = client.post(
        "/api/inbounds",
        headers=auth,
        json={
            "tag": "pytest-vmess",
            "protocol": "vmess",
            "port": 2087,
            "network": "ws",
            "security": "none",
            "remark": "Pytest VMess",
            "host": "cdn.test",
            "path": "/ws",
            "is_active": True,
        },
    )
    assert inbound.status_code == 201, inbound.text

    dns_tunnel = client.post(
        "/api/dns-tunnels",
        headers=auth,
        json={
            "name": "Subscription DNSTT",
            "domain": "dns.pytest.example.com",
            "upstream_port": 5398,
            "noizdns_enabled": True,
            "is_active": True,
        },
    )
    assert dns_tunnel.status_code == 201, dns_tunnel.text

    token = sample_user["sub_token"]
    info = client.get(f"/sub/{token}/info")
    assert info.status_code == 200
    assert len(info.json()["links"]) >= 1
    assert any("vmess://" in item["uri"] for item in info.json()["links"])
    assert len(info.json()["dns_links"]) == 2
    assert info.json()["dns_links"][0]["uri"].startswith("slipnet://")

    sub = client.get(f"/sub/{token}")
    assert sub.status_code == 200
    assert sub.headers["subscription-userinfo"].startswith("upload=")
    assert len(sub.text) > 20

    clash = client.get(f"/sub/{token}?format=clash")
    assert clash.status_code == 200
    assert "proxies:" in clash.text

    client.delete(f"/api/inbounds/{inbound.json()['id']}", headers=auth)
    client.delete(f"/api/dns-tunnels/{dns_tunnel.json()['id']}", headers=auth)


def test_node_agent_heartbeat_and_usage(client, auth, sample_user):
    node = client.post(
        "/api/nodes",
        headers=auth,
        json={"name": "Pytest Node", "address": "node.test", "port": 443, "api_port": 10086},
    )
    assert node.status_code == 201, node.text
    node_data = node.json()

    inbound = client.post(
        "/api/inbounds",
        headers=auth,
        json={
            "node_id": node_data["id"],
            "tag": "pytest-remote-vless",
            "protocol": "vless",
            "port": 9444,
            "network": "tcp",
            "security": "tls",
            "remark": "Remote TLS",
            "sni": "node.test",
            "is_active": True,
        },
    )
    assert inbound.status_code == 201, inbound.text

    node_config = client.get("/api/agent/config", headers={"X-Node-Key": node_data["api_key"]})
    assert node_config.status_code == 200, node_config.text
    payload = node_config.json()
    assert payload["hash"]
    assert payload["api_address"] == "127.0.0.1:10086"
    tags = [item["tag"] for item in payload["config"]["inbounds"]]
    assert "pytest-remote-vless" in tags
    assert "pytest-reality" not in tags

    heartbeat = client.post(
        "/api/agent/heartbeat",
        headers={"X-Node-Key": node_data["api_key"]},
        json={"cpu_usage": 12.5, "memory_usage": 32, "status": "online"},
    )
    assert heartbeat.status_code == 200

    usage = client.post(
        "/api/agent/usage",
        headers={"X-Node-Key": node_data["api_key"]},
        json={
            "entries": [
                {"uuid": sample_user["uuid"], "upload": 1024, "download": 2048},
            ]
        },
    )
    assert usage.status_code == 200
    assert usage.json()["updated"] == 1

    user = client.get(f"/api/users/{sample_user['id']}", headers=auth)
    assert user.json()["used_traffic_bytes"] == 3072

    client.delete(f"/api/inbounds/{inbound.json()['id']}", headers=auth)
    client.delete(f"/api/nodes/{node_data['id']}", headers=auth)


def test_dns_tunnel_setup_and_slipnet_links(client, auth):
    tunnel = client.post(
        "/api/dns-tunnels",
        headers=auth,
        json={
            "name": "Pytest DNSTT",
            "domain": "t.pytest.example.com",
            "upstream_port": 5399,
            "target_host": "127.0.0.1",
            "target_port": 1081,
            "mtu": 1232,
            "resolver": "8.8.8.8:53:0",
            "noizdns_enabled": True,
            "is_active": True,
        },
    )
    assert tunnel.status_code == 201, tunnel.text
    data = tunnel.json()
    assert len(data["private_key"]) == 64
    assert len(data["public_key"]) == 64

    setup = client.get(f"/api/dns-tunnels/{data['id']}/setup", headers=auth)
    assert setup.status_code == 200, setup.text
    setup_data = setup.json()
    assert "dnstt-server" in setup_data["command"]
    assert "t.pytest.example.com" in setup_data["dns_records"][1]

    uri = setup_data["client_uri_template_dnstt"]
    assert uri.startswith("slipnet://")
    fields = base64.b64decode(uri.removeprefix("slipnet://")).decode().split("|")
    assert len(fields) == 60
    assert fields[1] == "dnstt"
    assert fields[3] == "t.pytest.example.com"
    assert fields[11] == data["public_key"]

    noiz = setup_data["client_uri_template_noizdns"]
    assert noiz.startswith("slipnet://")
    noiz_fields = base64.b64decode(noiz.removeprefix("slipnet://")).decode().split("|")
    assert noiz_fields[1] == "sayedns"

    multiplexer = client.get("/api/dns-tunnels/multiplexer", headers=auth)
    assert multiplexer.status_code == 200
    routes = multiplexer.json()["routes"]
    assert any(route["domain"] == "t.pytest.example.com" for route in routes)

    links = client.get(f"/api/dns-tunnels/{data['id']}/user-links", headers=auth)
    assert links.status_code == 200
    assert links.json()["links"] == [] or links.json()["links"][0]["uri"].startswith("slipnet://")

    client.delete(f"/api/dns-tunnels/{data['id']}", headers=auth)


def test_reseller_scope_quota_credit_and_template(client, auth):
    plan = client.post(
        "/api/plans",
        headers=auth,
        json={
            "name": "Pytest Reseller Plan",
            "days": 10,
            "data_limit_bytes": 5 * 1024**3,
            "device_limit": 2,
            "price": 100000,
        },
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]

    reseller = client.post(
        "/api/admins",
        headers=auth,
        json={
            "username": "pytest_reseller",
            "password": "reseller-pass-123",
            "role": "reseller",
            "scope": "own",
            "max_users": 1,
            "credit": 500000,
        },
    )
    assert reseller.status_code == 201, reseller.text
    assert reseller.json()["is_owner"] is False
    assert "users.write" in reseller.json()["permissions"]

    login = client.post(
        "/api/auth/login",
        json={"username": "pytest_reseller", "password": "reseller-pass-123"},
    )
    assert login.status_code == 200
    reseller_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert login.json()["admin"]["credit"] == 500000

    # Scope isolation: no owner users are visible.
    listing = client.get("/api/users", headers=reseller_auth)
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    assert client.get("/api/nodes", headers=reseller_auth).status_code == 403

    first = client.post(
        "/api/users",
        headers=reseller_auth,
        json={"username": "reseller_customer_1", "plan_id": plan_id},
    )
    assert first.status_code == 201, first.text
    assert first.json()["data_limit_bytes"] == 5 * 1024**3
    me = client.get("/api/auth/me", headers=reseller_auth)
    assert me.json()["credit"] == 400000
    assert me.json()["user_count"] == 1

    second = client.post(
        "/api/users",
        headers=reseller_auth,
        json={"username": "reseller_customer_2"},
    )
    assert second.status_code == 403

    owner_patch = client.patch(
        f"/api/admins/{reseller.json()['id']}",
        headers=auth,
        json={"max_users": 10, "require_template": True},
    )
    assert owner_patch.status_code == 200, owner_patch.text

    without_plan = client.post(
        "/api/users",
        headers=reseller_auth,
        json={"username": "reseller_customer_3"},
    )
    assert without_plan.status_code == 400
    assert "پلن" in without_plan.json()["detail"]

    topup = client.post(
        f"/api/admins/{reseller.json()['id']}/credit",
        headers=auth,
        json={"amount": 250000, "note": "pytest topup"},
    )
    assert topup.status_code == 200, topup.text
    me = client.get("/api/auth/me", headers=reseller_auth)
    assert me.json()["credit"] == 650000


def test_multi_member_subscription_group(client, auth):
    first = client.post(
        "/api/users",
        headers=auth,
        json={"username": "group_member_1", "data_limit_bytes": 30 * 1024**3},
    )
    second = client.post(
        "/api/users",
        headers=auth,
        json={"username": "group_member_2", "data_limit_bytes": 30 * 1024**3},
    )
    third = client.post(
        "/api/users",
        headers=auth,
        json={"username": "group_member_3", "data_limit_bytes": 30 * 1024**3},
    )
    assert first.status_code == second.status_code == third.status_code == 201

    group = client.post(
        "/api/subscriptions",
        headers=auth,
        json={
            "name": "Pytest Family Group",
            "max_members": 2,
            "data_limit_bytes": 50 * 1024**3,
        },
    )
    assert group.status_code == 201, group.text
    group_data = group.json()
    assert group_data["max_members"] == 2

    added = client.post(
        f"/api/subscriptions/{group_data['id']}/members",
        headers=auth,
        json={"user_ids": [first.json()["id"], second.json()["id"]]},
    )
    assert added.status_code == 200, added.text
    assert len(added.json()["members"]) == 2

    overflow = client.post(
        f"/api/subscriptions/{group_data['id']}/members",
        headers=auth,
        json={"user_ids": [third.json()["id"]]},
    )
    assert overflow.status_code == 400

    info = client.get(f"/sub/{group_data['token']}/info")
    assert info.status_code == 200, info.text
    payload = info.json()
    assert payload["subscription_type"] == "group"
    assert payload["max_members"] == 2
    assert len(payload["members"]) == 2
    assert payload["data_limit_bytes"] == 50 * 1024**3

    raw = client.get(f"/sub/{group_data['token']}")
    assert raw.status_code == 200
    assert raw.headers["subscription-userinfo"].startswith("upload=")

    client.delete(f"/api/subscriptions/{group_data['id']}/members/{second.json()['id']}", headers=auth)
    replaced = client.post(
        f"/api/subscriptions/{group_data['id']}/members",
        headers=auth,
        json={"user_ids": [third.json()["id"]]},
    )
    assert replaced.status_code == 200
    assert len(replaced.json()["members"]) == 2


def test_settings_update(client, auth):
    response = client.put(
        "/api/settings",
        headers=auth,
        json={"panel_title": "SpecterGate Test", "default_expiry_days": 14},
    )
    assert response.status_code == 200
    assert response.json()["panel_title"] == "SpecterGate Test"
    assert response.json()["default_expiry_days"] == 14
