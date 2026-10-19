"""Optional contract checks against the pinned deployment binary."""
import json
import os
import subprocess

import pytest

from app.models import Inbound, VPNUser
from app.services.xray import _build_inbound, generate_keypair
from app.services.exports import export_profiles


@pytest.mark.skipif(not os.getenv("XRAY_TEST_BINARY"), reason="XRAY_TEST_BINARY not supplied")
@pytest.mark.parametrize("protocol", ["vless", "vmess", "trojan", "shadowsocks"])
@pytest.mark.parametrize("network", ["tcp", "ws", "grpc", "httpupgrade", "xhttp"])
def test_server_and_exported_client(tmp_path, protocol, network):
    user = VPNUser(id=1, username="contract", uuid="e3bc3070-d54e-433d-9767-066e8edfaad5", password="a-client-secret-123456", sub_token="a-subscription-token", is_active=True)
    inbound = Inbound(id=1, is_active=True, tag="contract", remark="Contract", listen="127.0.0.1", port=19999, protocol=protocol, network=network, security="none", path="/t", host="example.com", service_name="contract")
    built, _ = _build_inbound(inbound, [user])
    server = {"inbounds": [built], "outbounds": [{"protocol": "freedom"}]}
    client = export_profiles([user], [inbound], {}, "127.0.0.1", "json")[0]
    for label, payload in [("server", server), ("client", client)]:
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run([os.environ["XRAY_TEST_BINARY"], "run", "-test", "-c", str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not os.getenv("XRAY_TEST_BINARY"), reason="XRAY_TEST_BINARY not supplied")
@pytest.mark.parametrize("network", ["tcp", "xhttp"])
def test_reality_contract(tmp_path, network):
    keys = generate_keypair()
    user = VPNUser(id=1, username="contract", uuid="e3bc3070-d54e-433d-9767-066e8edfaad5", password="a-client-secret-123456", sub_token="a-subscription-token", is_active=True)
    inbound = Inbound(id=1, is_active=True, tag="reality", remark="Reality", port=19999, protocol="vless", network=network, security="reality", sni="example.com", reality_dest="example.com:443", reality_private_key=keys["private_key"], reality_public_key=keys["public_key"], reality_short_id=keys["short_id"], flow="xtls-rprx-vision" if network == "tcp" else None)
    server, _ = _build_inbound(inbound, [user])
    for label, payload in [("server", {"inbounds": [server], "outbounds": [{"protocol": "freedom"}]}), ("client", export_profiles([user], [inbound], {}, "example.com", "json")[0])]:
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run([os.environ["XRAY_TEST_BINARY"], "run", "-test", "-c", str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
