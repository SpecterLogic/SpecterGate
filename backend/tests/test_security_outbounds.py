import ast
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import uuid

import pytest

from app.database import SessionLocal
from app.models import ProtectedSetting
from app.services import fail2ban
from app.services.routing import apply_to_xray, outbound_secret, redact_config
from app.services.vault import get_secret


def admin_headers(client, owner, permissions):
    username = 'delegate_' + uuid.uuid4().hex[:8]
    response = client.post('/api/admins', headers=owner, json={'username': username, 'password': 'delegate-password-123', 'role': 'admin', 'permissions': permissions})
    assert response.status_code == 201, response.text
    login = client.post('/api/auth/login', json={'username': username, 'password': 'delegate-password-123'})
    return {'Authorization': 'Bearer ' + login.json()['access_token']}


def test_fail2ban_delegated_access_and_validation(client, auth, monkeypatch):
    calls = []
    def fake(action, **kwargs):
        calls.append((action, kwargs))
        return {'available': True, 'active': True, 'banned_ips': []} if action == 'status' else {'ok': True}
    monkeypatch.setattr(fail2ban, 'command', fake)
    viewer = admin_headers(client, auth, ['security.read', 'routing.read'])
    assert client.get('/api/security/fail2ban', headers=viewer).status_code == 200
    assert client.post('/api/security/fail2ban/ban', headers=viewer, json={'ip': '8.8.4.4'}).status_code == 403
    assert client.put('/api/routing', headers=viewer, json={}).status_code == 403
    manager = admin_headers(client, auth, ['security.manage'])
    assert client.get('/api/security/fail2ban', headers=manager).status_code == 200
    assert client.post('/api/security/fail2ban/ban', headers=manager, json={'ip': '127.0.0.1'}).status_code == 422
    assert client.post('/api/security/fail2ban/ban', headers=manager, json={'ip': '8.8.4.4; whoami'}).status_code == 422
    response = client.post('/api/security/fail2ban/unban', headers=manager, json={'ip': '8.8.4.4'})
    assert response.status_code == 200 and calls[-1] == ('unban', {'ip': '8.8.4.4'})
    assert client.put('/api/security/fail2ban', headers=manager, json={'maxretry': 1, 'findtime': 600, 'bantime': 3600}).status_code == 422
    assert client.get('/api/security/fail2ban').status_code == 401


def test_custom_outbound_credentials_and_native_validation(client, auth, tmp_path):
    password = 'proxy-private-password-123'
    payload = {'default_outbound': 'ipv4', 'outbounds': [{'tag': 'proxy-test-socks', 'name': 'Test SOCKS', 'protocol': 'socks', 'address': '127.0.0.1', 'port': 1086, 'username': 'proxy-user', 'password': password}, {'tag': 'proxy-test-http', 'name': 'Test HTTP', 'protocol': 'http', 'address': '127.0.0.1', 'port': 3128}]}
    response = client.put('/api/routing/outbounds', headers=auth, json=payload)
    assert response.status_code == 200, response.text
    assert password not in response.text
    assert response.json()['outbounds'][0]['password_configured'] is True
    with SessionLocal() as db:
        assert get_secret(db, outbound_secret('proxy-test-socks')) == password
        assert password not in db.get(ProtectedSetting, outbound_secret('proxy-test-socks')).ciphertext
        config = {'outbounds': [{'tag': 'direct', 'protocol': 'freedom'}, {'tag': 'blocked', 'protocol': 'blackhole'}], 'routing': {'rules': []}}
        apply_to_xray(db, config)
    assert password not in json.dumps(redact_config(config))
    assert password in json.dumps(config)
    if os.getenv('XRAY_TEST_BINARY'):
        path = tmp_path / 'proxy-outbounds.json'; path.write_text(json.dumps(config), encoding='utf-8')
        result = subprocess.run([os.environ['XRAY_TEST_BINARY'], 'run', '-test', '-c', str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
    # Referenced outbounds cannot disappear silently.
    policy = response.json(); policy['rules'] = [{'outbound': 'proxy-test-socks', 'domains': ['domain:example.com']}]
    assert client.put('/api/routing', headers=auth, json=policy).status_code == 200
    assert client.put('/api/routing/outbounds', headers=auth, json={'default_outbound': 'ipv4', 'outbounds': []}).status_code == 422
    assert client.put('/api/routing', headers=auth, json={}).status_code == 200
    assert client.put('/api/routing/outbounds', headers=auth, json={'default_outbound': 'ipv4', 'outbounds': []}).status_code == 200


def test_bridge_rejects_arbitrary_commands_and_jails():
    source = Path(__file__).resolve().parents[2] / 'deploy/security_bridge.py'
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'dispatch')
    commands = []
    namespace = {'ipaddress': ipaddress, 'run': lambda *args: commands.append(args) or ''}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    dispatch = namespace['dispatch']
    for data in [{'action': 'stop'}, {'action': 'ban', 'ip': '127.0.0.1'}, {'action': 'unban', 'ip': '8.8.8.8;id'}, {'action': 'unban', 'jail': 'sshd;id', 'ip': '8.8.8.8'}]:
        with pytest.raises(ValueError): dispatch(data)
    assert not commands
    dispatch({'action': 'unban', 'ip': '8.8.4.4'})
    assert commands == [('set', 'sshd', 'unbanip', '8.8.4.4')]
