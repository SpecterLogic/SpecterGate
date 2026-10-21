import json
import os
import subprocess
from pathlib import Path

import pytest
from app.database import SessionLocal
from app.services.hosts_dns import DnsConfig, HostEntry, get_dns_config, save_dns_config
from app.services.xray import generate_config


def test_get_dns_config_default(client, auth):
    response = client.get("/api/dns-hosts", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert "servers" in data
    assert len(data["servers"]) > 0
    assert data["query_strategy"] == "UseIP"
    assert data["hosts"] == []


def test_update_dns_config(client, auth):
    payload = {
        "servers": ["1.1.1.1", "8.8.4.4", "https://dns.quad9.net/dns-query"],
        "hosts": [
            {"domain": "example.com", "ips": ["93.184.216.34"]},
            {"domain": "domain:google.com", "ips": ["142.250.190.46", "142.250.190.47"]},
        ],
        "query_strategy": "UseIPv4",
        "disable_cache": True,
        "disable_fallback": False,
        "client_ip": "1.2.3.4",
        "tag": "custom_dns",
    }
    response = client.put("/api/dns-hosts", json=payload, headers=auth)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_strategy"] == "UseIPv4"
    assert len(res_data["hosts"]) == 2
    assert res_data["disable_cache"] is True

    # Check that GET returns updated config
    get_res = client.get("/api/dns-hosts", headers=auth)
    assert get_res.status_code == 200
    assert get_res.json()["client_ip"] == "1.2.3.4"


def test_upsert_and_delete_host_entry(client, auth):
    # Add new host
    host_payload = {"domain": "speedtest.net", "ips": ["151.101.2.219"]}
    post_res = client.post("/api/dns-hosts/hosts", json=host_payload, headers=auth)
    assert post_res.status_code == 200
    hosts = post_res.json()
    assert any(h["domain"] == "speedtest.net" for h in hosts)

    # Update the same host
    updated_payload = {"domain": "speedtest.net", "ips": ["151.101.66.219", "151.101.130.219"]}
    post_res2 = client.post("/api/dns-hosts/hosts", json=updated_payload, headers=auth)
    assert post_res2.status_code == 200
    hosts2 = post_res2.json()
    entry = next(h for h in hosts2 if h["domain"] == "speedtest.net")
    assert len(entry["ips"]) == 2

    # Delete host
    del_res = client.delete("/api/dns-hosts/hosts/speedtest.net", headers=auth)
    assert del_res.status_code == 200
    remaining_hosts = del_res.json()
    assert not any(h["domain"] == "speedtest.net" for h in remaining_hosts)


def test_validation_invalid_server_and_host(client, auth):
    # Invalid server format
    bad_server = {
        "servers": ["not-a-valid-dns-server%%%"],
        "hosts": [],
        "query_strategy": "UseIP",
    }
    res = client.put("/api/dns-hosts", json=bad_server, headers=auth)
    assert res.status_code == 422

    # Invalid IP in host
    bad_host = {"domain": "test.com", "ips": ["999.999.999.999"]}
    res2 = client.post("/api/dns-hosts/hosts", json=bad_host, headers=auth)
    assert res2.status_code == 422


def test_xray_config_integration_with_dns(client, auth, tmp_path):
    # Configure custom DNS and hosts
    payload = {
        "servers": ["1.1.1.1", "8.8.8.8", "https://1.1.1.1/dns-query"],
        "hosts": [
            {"domain": "domain:cloudflare.com", "ips": ["104.16.132.229"]},
            {"domain": "local.lan", "ips": ["192.168.1.1"]},
        ],
        "query_strategy": "UseIP",
        "disable_cache": False,
    }
    client.put("/api/dns-hosts", json=payload, headers=auth)

    with SessionLocal() as db:
        config, warnings, inbounds, clients = generate_config(db)

    assert "dns" in config
    assert config["dns"]["servers"] == ["1.1.1.1", "8.8.8.8", "https://1.1.1.1/dns-query"]
    assert config["dns"]["hosts"]["domain:cloudflare.com"] == "104.16.132.229"
    assert config["dns"]["hosts"]["local.lan"] == "192.168.1.1"

    # If Xray test binary is present, test with live xray
    binary = os.getenv("XRAY_TEST_BINARY")
    if binary and Path(binary).exists():
        test_file = tmp_path / "xray_dns_test.json"
        test_file.write_text(json.dumps(config), encoding="utf-8")
        result = subprocess.run([binary, "run", "-test", "-c", str(test_file)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
