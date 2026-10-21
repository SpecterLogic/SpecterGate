import json
import os
import subprocess
import socket
import time
from pathlib import Path

import pytest
from app.database import SessionLocal
from app.services.routing import RoutingConfig, profile_keys
from app.services.settings import set_setting
from app.services.xray import generate_config
from app.services import xray_rpc, xray
import grpc


@pytest.fixture
def native_routing(monkeypatch, tmp_path, sample_user):
    binary = os.getenv("XRAY_TEST_BINARY")
    if not binary:
        pytest.skip("Native Xray binary required for route diagnostics")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        vless_port = probe.getsockname()[1]
    monkeypatch.setattr(xray.settings, "xray_api_address", f"127.0.0.1:{port}")
    config = {
        "api": {"tag": "api", "services": ["RoutingService", "StatsService"]}, "stats": {},
        "policy": {"levels": {"0": {"statsUserOnline": True, "statsUserUplink": True, "statsUserDownlink": True}}},
        "inbounds": [{"tag": "api", "listen": "127.0.0.1", "port": port, "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"}}],
        "outbounds": [{"tag": "direct", "protocol": "freedom"}, {"tag": "blocked", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "AsIs", "rules": [
            {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
            {"type": "field", "ip": ["192.168.0.0/16"], "outboundTag": "blocked"},
            {"type": "field", "user": ["limited-user"], "source": ["203.0.113.7"], "outboundTag": "blocked"},
            {"type": "field", "inboundTag": ["restricted"], "port": "8443", "outboundTag": "blocked"},
            {"type": "field", "domain": ["domain:ads.example.com"], "outboundTag": "blocked"},
            {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
        ]},
    }
    config["inbounds"].append({"tag": "native-vless", "listen": "127.0.0.1", "port": vless_port, "protocol": "vless", "settings": {"decryption": "none", "clients": [{"id": sample_user["uuid"], "email": sample_user["uuid"], "level": 0}]}})
    path = tmp_path / "routing-native.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    process = subprocess.Popen([binary, "run", "-c", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                xray_rpc.online_users()
                break
            except grpc.RpcError:
                if process.poll() is not None:
                    pytest.fail("Native core failed to start")
                time.sleep(0.1)
        else:
            pytest.fail("Native API did not become ready")
        monkeypatch.setattr(xray, "xray_status", lambda: {"running": True})
        yield {"config": config, "path": path, "process": process, "vless_port": vless_port, "user": sample_user}
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_test_route_private_ip(client, auth, native_routing):
    payload = {"target_ip": "192.168.1.10", "target_port": 80}
    res = client.post("/api/diagnostics/test-route", json=payload, headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["outbound"] == "blocked"
    assert data["matched"] is True
    assert data["rule_name"] == "Xray RoutingService.TestRoute"


def test_test_route_custom_rule(client, auth, native_routing):
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
    assert res2.json()["matched"] is True


def test_native_route_respects_missing_fields_and_user_ip_blocks(native_routing):
    assert xray_rpc.route("example.com", port=8443).outbound_tag == "direct"
    assert xray_rpc.route("example.com", inbound="restricted").outbound_tag == "direct"
    assert xray_rpc.route("example.com", port=8443, inbound="restricted").outbound_tag == "blocked"
    assert xray_rpc.route("example.com", user="limited-user", source_ip="203.0.113.7").outbound_tag == "blocked"
    assert xray_rpc.route("example.com", user="other-user", source_ip="203.0.113.7").outbound_tag == "direct"
    assert xray_rpc.online_users() == []


def test_live_online_ips_limits_and_real_disconnect(native_routing, monkeypatch, tmp_path):
    import copy
    import socketserver
    import struct
    import threading
    import uuid
    from app.models import VPNUser
    from app.services import monitoring, maintenance
    from app.routers.monitoring import enforce_disconnect

    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(1024):
                self.request.sendall(data)

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opened = []

    def connect(source):
        connection = socket.socket()
        connection.settimeout(3)
        connection.bind((source, 0))
        connection.connect(("127.0.0.1", native_routing["vless_port"]))
        request = b"\x00" + uuid.UUID(native_routing["user"]["uuid"]).bytes + b"\x00\x01" + struct.pack(">H", server.server_address[1]) + b"\x01" + socket.inet_aton("127.0.0.1") + b"ping"
        connection.sendall(request)
        response = b""
        while len(response) < 6:
            part = connection.recv(1024)
            if not part:
                break
            response += part
        assert response == b"\x00\x00ping", response
        opened.append(connection)
        return connection

    try:
        first = connect("127.0.0.2")
        second = connect("127.0.0.3")
        email = native_routing["user"]["uuid"]
        assert email in xray_rpc.online_users()
        assert set(xray_rpc.online_ips(email)) == {"127.0.0.2", "127.0.0.3"}
        with SessionLocal() as db:
            user = db.get(VPNUser, native_routing["user"]["id"])
            assert monitoring.refresh_from_core(db) is False
            assert len(monitoring.get_active_sessions(user.id)) == 2
            user.device_limit = 1
            db.commit()
            assert monitoring.refresh_from_core(db) is True
            assert len(monitoring.get_active_sessions(user.id)) == 1
            assert monitoring.blocked_rules(db)

            def generated(db):
                config = copy.deepcopy(native_routing["config"])
                config["routing"]["rules"][1:1] = monitoring.blocked_rules(db)
                return config, [], [], 1

            monkeypatch.setattr(maintenance, "reconcile", lambda: None)
            monkeypatch.setattr(xray, "generate_config", generated)
            monkeypatch.setattr(xray, "_process", native_routing["process"])
            monkeypatch.setattr(xray.settings, "xray_enabled", True)
            monkeypatch.setattr(xray.settings, "xray_binary", os.environ["XRAY_TEST_BINARY"])
            monkeypatch.setattr(xray.settings, "xray_config_path", str(native_routing["path"]))
            monkeypatch.setattr(xray.settings, "xray_log_path", str(tmp_path / "disconnect-core.log"))
            enforce_disconnect(db, [(user, "127.0.0.2")])
            assert native_routing["process"].poll() is not None
            for connection in (first, second):
                try:
                    assert connection.recv(1) == b""
                except ConnectionResetError:
                    pass
            assert xray_rpc.route("example.com", user=email, source_ip="127.0.0.2").outbound_tag == "blocked"
    finally:
        for connection in opened:
            connection.close()
        if xray._process is not None:
            xray.stop_process()
        server.shutdown()
        server.server_close()


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
