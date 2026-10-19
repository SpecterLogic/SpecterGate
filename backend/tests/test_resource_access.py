import base64
import uuid

from app.database import SessionLocal
from app.models import VPNUser


def unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:7]}"


def test_user_group_config_and_tunnel_intersection(client, auth):
    inbounds = []
    for i in range(3):
        response = client.post("/api/inbounds", headers=auth, json={"tag": unique("access"), "protocol": "vless", "network": "tcp", "security": "none", "port": 22500 + i, "remark": unique("config")})
        assert response.status_code == 201, response.text
        inbounds.append(response.json())
    tunnels = []
    for i in range(2):
        domain = unique("t").replace("_", "-") + ".example.com"
        response = client.post("/api/dns-tunnels", headers=auth, json={"name": unique("dns"), "domain": domain, "upstream_port": 5550 + i})
        assert response.status_code == 201, response.text
        tunnels.append(response.json())
    group = client.post("/api/subscriptions", headers=auth, json={"name": unique("group"), "max_members": 2, "allowed_inbound_ids": [inbounds[1]["id"], inbounds[2]["id"]], "allowed_dns_tunnel_ids": [tunnels[1]["id"]]}).json()
    result = client.post("/api/users", headers=auth, json={"username": unique("customer"), "subscription_id": group["id"], "allowed_inbound_ids": [inbounds[0]["id"], inbounds[1]["id"]], "allowed_dns_tunnel_ids": [tunnels[0]["id"], tunnels[1]["id"]]})
    assert result.status_code == 201, result.text
    user = result.json()
    assert user["subscription_path"] == f"/sub/{user['sub_token']}"
    assert user["group_subscription_path"] == f"/sub/{group['token']}"
    info = client.get(f"/sub/{user['sub_token']}/info").json()
    assert len(info["links"]) == 1
    assert info["links"][0]["remark"] == f"{inbounds[1]['remark']} | {user['username']}"
    assert {link["id"] for link in info["dns_links"]} == {tunnels[1]["id"]}
    assert info["format_urls"]["singbox"].endswith("?format=singbox")
    for format in ["raw", "json", "clash", "singbox", "base64"]:
        response = client.get(f"/sub/{user['sub_token']}", params={"format": format}, headers={"User-Agent": "clash"})
        assert response.status_code == 200, response.text
        text = base64.b64decode(response.text).decode() if format == "base64" else response.text
        assert inbounds[0]["remark"] not in text
        assert inbounds[2]["remark"] not in text
    dns = client.get(f"/sub/{user['sub_token']}?format=dnstt")
    assert dns.status_code == 200
    decoded = base64.b64decode(dns.text.removeprefix("slipnet://")).decode()
    assert tunnels[1]["domain"] in decoded
    assert tunnels[0]["domain"] not in decoded
    generated = client.get("/api/xray/config", headers=auth).json()["config"]["inbounds"]
    for item in generated:
        clients = item.get("settings", {}).get("clients", [])
        if item["tag"] in [inbound["tag"] for inbound in inbounds]:
            assert any(c.get("id") == user["uuid"] for c in clients) == (item["tag"] == inbounds[1]["tag"])
    denied = client.patch(f"/api/users/{user['id']}", headers=auth, json={"allowed_inbound_ids": [], "allowed_dns_tunnel_ids": []})
    assert denied.status_code == 200
    payload = client.get(f"/sub/{user['sub_token']}/info").json()
    assert payload["links"] == payload["dns_links"] == []
    assert client.get(f"/sub/{user['sub_token']}?format=dnstt").status_code == 422
    assert client.patch(f"/api/users/{user['id']}", headers=auth, json={"allowed_inbound_ids": None}).status_code == 200
    assert len(client.get(f"/sub/{user['sub_token']}/info").json()["links"]) == 2


def test_revoke_individual_does_not_revoke_group(client, auth, sample_user):
    group = client.post("/api/subscriptions", headers=auth, json={"name": unique("group")}).json()
    client.post(f"/api/subscriptions/{group['id']}/members", headers=auth, json={"user_ids": [sample_user["id"]]})
    changed = client.post(f"/api/users/{sample_user['id']}/revoke-subscription", headers=auth)
    assert changed.status_code == 200
    assert changed.json()["sub_token"] != sample_user["sub_token"]
    assert client.get(f"/sub/{sample_user['sub_token']}/info").status_code == 404
    assert client.get(f"/sub/{group['token']}/info").status_code == 200


def test_invalid_resource_assignment_rolls_back(client, auth, sample_user):
    response = client.patch(f"/api/users/{sample_user['id']}", headers=auth, json={"note": "must not persist", "allowed_inbound_ids": [99999999]})
    assert response.status_code == 404
    result = client.get(f"/api/users/{sample_user['id']}", headers=auth).json()
    assert result["note"] == sample_user["note"]
    assert result["allowed_inbound_ids"] is None


def test_reseller_cannot_assign_inbound_outside_parent_scope(client, auth):
    response = client.post("/api/admins", headers=auth, json={"username": unique("limited"), "password": "limited-pass-123", "allowed_inbound_ids": []})
    assert response.status_code == 201
    username = response.json()["username"]
    login = client.post("/api/auth/login", json={"username": username, "password": "limited-pass-123"})
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}
    options = client.get("/api/users/access-options", headers=token)
    assert options.status_code == 200
    assert options.json()["inbounds"] == []
    inbound = client.get("/api/inbounds", headers=auth).json()[0]
    assigned = client.post("/api/users", headers=token, json={"username": unique("invalid"), "allowed_inbound_ids": [inbound["id"]]})
    assert assigned.status_code == 403
