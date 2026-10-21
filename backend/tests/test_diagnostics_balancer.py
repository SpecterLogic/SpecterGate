import json
import os
import subprocess
from pathlib import Path

import pytest
from app.database import SessionLocal
from app.services.routing import RoutingConfig, profile_keys
from app.services.settings import set_setting
from app.services.xray import generate_config


def test_test_route_private_ip(client, auth):
    payload = {"target_ip": "192.168.1.10", "target_port": 80}
    res = client.post("/api/diagnostics/test-route", json=payload, headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["outbound"] == "blocked"
    assert data["matched"] is True
    assert "Private" in data["reason"]


def test_test_route_custom_rule(client, auth):
    with SessionLocal() as db:
        key, _ = profile_keys(None)
        cfg = {
            "default_outbound": "direct",
            "rules": [
                {
                    "outbound": "blocked",
                    "domains": ["domain:ads.example.com"],
                    "ips": [],
                    "inbound_ids": [],
                }
            ],
        }
        set_setting(db, key, cfg)
        db.commit()

    # Test match
    res = client.post("/api/diagnostics/test-route", json={"target_domain": "ads.example.com"}, headers=auth)
    assert res.status_code == 200
    assert res.json()["outbound"] == "blocked"
    assert res.json()["matched"] is True

    # Test non-match (fallback)
    res2 = client.post("/api/diagnostics/test-route", json={"target_domain": "goodsite.org"}, headers=auth)
    assert res2.status_code == 200
    assert res2.json()["outbound"] == "direct"
    assert res2.json()["matched"] is False


def test_ping_localhost(client, auth):
    # Test ping to localhost
    payload = {"host": "127.0.0.1", "port": 10085, "timeout_sec": 1.0}
    res = client.post("/api/diagnostics/ping", json=payload, headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert "reachable" in data
    assert data["host"] == "127.0.0.1"


def test_update_and_list_balancers(client, auth):
    balancers_payload = [
        {
            "tag": "balancer-test",
            "name": "Test Balancer",
            "selector": ["direct", "blocked"],
            "strategy": "leastPing",
        }
    ]
    put_res = client.put("/api/diagnostics/balancers", json=balancers_payload, headers=auth)
    assert put_res.status_code == 200, put_res.text
    assert len(put_res.json()) == 1
    assert put_res.json()[0]["tag"] == "balancer-test"

    get_res = client.get("/api/diagnostics/balancers", headers=auth)
    assert get_res.status_code == 200
    assert get_res.json()[0]["strategy"] == "leastPing"


def test_xray_config_generation_with_balancer_and_chaining(client, auth, tmp_path):
    with SessionLocal() as db:
        key, _ = profile_keys(None)
        cfg = {
            "default_outbound": "direct",
            "balancers": [
                {
                    "tag": "balancer-stream",
                    "name": "Stream Balancer",
                    "selector": ["direct", "blocked"],
                    "strategy": "roundRobin",
                }
            ],
            "outbounds": [
                {
                    "tag": "proxy-socks-chained",
                    "name": "Chained SOCKS",
                    "protocol": "socks",
                    "address": "127.0.0.1",
                    "port": 10808,
                    "chain_proxy": "direct",
                }
            ],
            "rules": [
                {
                    "outbound": "balancer-stream",
                    "domains": ["domain:video.com"],
                    "ips": [],
                    "inbound_ids": [],
                }
            ],
        }
        set_setting(db, key, cfg)
        db.commit()

        config, warnings, inbounds, clients = generate_config(db)

    assert "balancers" in config["routing"]
    assert config["routing"]["balancers"][0]["tag"] == "balancer-stream"
    
    # Check rule uses balancerTag
    balancer_rule = next(r for r in config["routing"]["rules"] if r.get("balancerTag") == "balancer-stream")
    assert "domain:video.com" in balancer_rule["domain"]

    # Check proxySettings in chained outbound
    chained_outbound = next(o for o in config["outbounds"] if o["tag"] == "proxy-socks-chained")
    assert chained_outbound["proxySettings"]["tag"] == "direct"

    # Test with real xray binary
    binary = os.getenv("XRAY_TEST_BINARY")
    if binary and Path(binary).exists():
        test_file = tmp_path / "xray_balancer_test.json"
        test_file.write_text(json.dumps(config), encoding="utf-8")
        result = subprocess.run([binary, "run", "-test", "-c", str(test_file)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
