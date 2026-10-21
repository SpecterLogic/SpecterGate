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
def native_routing(monkeypatch, tmp_path, sample_user, request):
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
    variant = getattr(request, "param", "raw")
    network = "kcp" if variant == "masked-kcp" else "raw" if variant in {"masked-raw", "encrypted-raw"} else variant
    stream = {"network": network, "security": "none"}
    if network == "ws":
        stream["wsSettings"] = {"path": "/flow"}
    elif network == "xhttp":
        stream["xhttpSettings"] = {"path": "/flow", "mode": "auto"}
    encryption = "none"
    if variant == "masked-raw":
        stream["finalmask"] = {"tcp": [{"type": "sudoku", "settings": {"password": "native-test-mask-password"}}]}
    if variant == "masked-kcp":
        stream["finalmask"] = {"udp": [{"type": "salamander", "settings": {"password": "native-test-mask-password"}}]}
    if variant == "encrypted-raw":
        from app.services.core_crypto import generate
        monkeypatch.setattr(xray.settings, "xray_binary", binary)
        pair = generate("vlessenc")
        config["inbounds"][-1]["settings"]["decryption"] = pair["vless_decryption"]
        encryption = pair["vless_encryption"]
    config["inbounds"][-1]["streamSettings"] = stream
    other_uuid = "ed0c32b1-cb18-4ea8-a00d-98619cc0ece1"
    config["inbounds"][-1]["settings"]["clients"].append({"id": other_uuid, "email": other_uuid, "level": 0})
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
        from app.services import session_control
        if session_control.available():
            session_control.call("Configure", {"limits": {}, "blocks": []})
        monkeypatch.setattr(xray, "xray_status", lambda: {"running": True})
        yield {"config": config, "path": path, "process": process, "vless_port": vless_port, "user": sample_user, "other_uuid": other_uuid, "stream": stream, "encryption": encryption}
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
    import socketserver
    import struct
    import threading
    import uuid
    from app.models import VPNUser
    from app.services import monitoring, session_control
    from app.routers.monitoring import enforce_disconnect
    if not session_control.available():
        pytest.skip("Managed core required for targeted flow control")

    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(1024):
                self.request.sendall(data)

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    opened = []

    def connect(source, user_uuid=None):
        connection = socket.socket()
        connection.settimeout(3)
        connection.bind((source, 0))
        connection.connect(("127.0.0.1", native_routing["vless_port"]))
        request = b"\x00" + uuid.UUID(user_uuid or native_routing["user"]["uuid"]).bytes + b"\x00\x01" + struct.pack(">H", server.server_address[1]) + b"\x01" + socket.inet_aton("127.0.0.1") + b"ping"
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

    def closed(connection):
        try:
            assert connection.recv(1) == b""
        except ConnectionResetError:
            pass

    try:
        first = connect("127.0.0.2")
        second = connect("127.0.0.3")
        other = connect("127.0.0.2", native_routing["other_uuid"])
        with SessionLocal() as db:
            user = db.get(VPNUser, native_routing["user"]["id"])
            monitoring.refresh_from_core(db)
            assert len(monitoring.get_active_sessions(user.id)) == 2
            user.device_limit = 1
            db.commit()
            monitoring.refresh_from_core(db)
            closed(second)
            first.sendall(b"still-alive")
            assert first.recv(1024) == b"still-alive"
            assert native_routing["process"].poll() is None
            assert len(monitoring.get_active_sessions(user.id)) == 1
            # A denied new IP cannot disturb an admitted connection.
            with pytest.raises((AssertionError, ConnectionResetError)):
                connect("127.0.0.4")
            first.sendall(b"survived-admission")
            assert first.recv(1024) == b"survived-admission"
            enforce_disconnect(db, [(user, "127.0.0.2")])
            closed(first)
            other.sendall(b"other-user-same-ip")
            assert other.recv(1024) == b"other-user-same-ip"
            assert native_routing["process"].poll() is None
            with pytest.raises((AssertionError, ConnectionResetError)):
                connect("127.0.0.2")
            other.close()
            for _ in range(30):
                if not session_control.call("Snapshot")["flows"]:
                    break
                time.sleep(0.1)
            assert not session_control.call("Snapshot")["flows"]
    finally:
        for connection in opened:
            connection.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("native_routing", ["raw", "ws", "xhttp", "masked-raw", "masked-kcp", "encrypted-raw"], indirect=True)
def test_transport_and_mux_user_isolation(native_routing, tmp_path):
    import socketserver
    import struct
    import threading
    from app.services import session_control
    if not session_control.available():
        pytest.skip("Managed core required")

    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(1024):
                self.request.sendall(data)

    echo = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
    echo.daemon_threads = True
    threading.Thread(target=echo.serve_forever, daemon=True).start()
    processes, connections = [], []

    def connect(user, index):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = {
            "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks", "settings": {"auth": "noauth"}}],
            "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": "127.0.0.1", "port": native_routing["vless_port"], "users": [{"id": user, "encryption": native_routing["encryption"]}]}]}, "streamSettings": native_routing["stream"], "mux": {"enabled": native_routing["stream"]["network"] != "xhttp", "concurrency": 8}}],
        }
        path = tmp_path / f"client-{index}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        process = subprocess.Popen([os.environ["XRAY_TEST_BINARY"], "run", "-c", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        for _ in range(40):
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=3)
                break
            except OSError:
                assert process.poll() is None
                time.sleep(.1)
        else:
            pytest.fail("Client SOCKS did not start")
        connections.append(connection)
        connection.sendall(b"\x05\x01\x00")
        assert connection.recv(2) == b"\x05\x00"
        connection.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack(">H", echo.server_address[1]))
        response = b""
        while len(response) < 10:
            part = connection.recv(10-len(response))
            assert part, "SOCKS connection closed during handshake"
            response += part
        assert response[:2] == b"\x05\x00"
        connection.sendall(b"hello")
        assert connection.recv(5) == b"hello"
        return connection

    try:
        first = connect(native_routing["user"]["uuid"], 1)
        other = connect(native_routing["other_uuid"], 2)
        session_control.call("Configure", {"limits": {}, "blocks": [{"user": native_routing["user"]["uuid"], "ip": "127.0.0.1", "until": time.time()+600}]})
        try:
            assert first.recv(1) == b""
        except ConnectionResetError:
            pass
        other.sendall(b"survived")
        assert other.recv(8) == b"survived"
        assert native_routing["process"].poll() is None
    finally:
        for connection in connections:
            connection.close()
        for process in processes:
            process.terminate()
            process.wait(timeout=10)
        echo.shutdown()
        echo.server_close()


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
