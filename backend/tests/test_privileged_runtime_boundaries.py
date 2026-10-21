import ast
import base64
import ipaddress
from pathlib import Path
import re
import time
from types import SimpleNamespace

import pytest


def functions(file, names, namespace):
    source = Path(__file__).resolve().parents[2] / "deploy" / file
    parsed = ast.parse(source.read_text(encoding="utf-8"))
    tree = ast.Module(body=[item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name in names], type_ignores=[])
    exec(compile(tree, str(source), "exec"), namespace)
    return namespace


def test_awg_companion_rejects_other_pools_and_invalid_parameters():
    scope = functions("wireguard_agent.py", {"validated_peers", "validated_params"}, {"time": time, "base64": base64, "ipaddress": ipaddress})
    key = base64.b64encode(bytes(range(32))).decode()
    manifest = {"updated_at": time.time(), "peers": [{"public_key": key, "address": "10.89.0.2"}]}
    assert scope["validated_peers"](manifest, True) == [(key, "10.89.0.2")]
    with pytest.raises(ValueError):
        scope["validated_peers"](manifest, False)
    manifest["updated_at"] = 0
    assert scope["validated_peers"](manifest, True) == []
    from app.services.amneziawg import AmneziaWgParams
    params = AmneziaWgParams().model_dump()
    assert scope["validated_params"](params, 51821) == params
    for invalid in ({**params, "h4": 5544332211}, {**params, "h2": params["h1"]}, {**params, "server_address": "10.88.0.1/16"}, {**params, "port": 22}):
        with pytest.raises(ValueError):
            scope["validated_params"](invalid, 51821)


def test_certificate_bridge_has_fixed_commands_and_validates_before_execution():
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert not kwargs.get("shell")
        return SimpleNamespace(returncode=0)
    scope = functions("ssl_bridge.py", {"validate_domain", "dispatch"}, {"re": re, "Path": Path, "subprocess": SimpleNamespace(run=run), "logging": __import__("logging")})
    dispatch = scope["dispatch"]
    for invalid in ("--help", "../../etc", "bad\nname.example", "bad;id.example", "-bad.example", "example.com/", "example..com"):
        with pytest.raises(ValueError):
            dispatch({"action": "issue", "domain": invalid})
    with pytest.raises(ValueError):
        dispatch({"action": "restart", "domain": "vpn.example.com"})
    assert calls == []
    result = dispatch({"action": "issue", "domain": "vpn.example.com", "email": "admin@example.com"})
    assert calls[0][0][0] == "/usr/bin/certbot"
    assert "--nginx" in calls[0][0] and "--standalone" not in calls[0][0]
    assert calls[1][0] == ["/usr/local/lib/spectergate-ssl-deploy.py", "vpn.example.com"]
    assert Path(result["key_path"]).name == "privkey.pem"
