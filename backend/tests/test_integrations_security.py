import base64
import io
import json
import os
import subprocess
import tarfile
import time
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from app.database import SessionLocal
from app.models import VPNUser, ProtectedSetting
from app.services import telegram_bot, vault
from app.services.backup_crypto import encrypt_archive, decrypt_archive
from app.services.settings import set_setting
from app.services.routing import apply_to_xray, redact_config


def test_logout_revokes_bearer(client, auth):
    assert client.get('/api/auth/me', headers=auth).status_code == 200
    assert client.post('/api/auth/logout', headers=auth).status_code == 200
    assert client.get('/api/auth/me', headers=auth).status_code == 401


def test_request_security(client, auth):
    response = client.get('/api/auth/me', headers=auth)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-frame-options'] == 'DENY'
    assert "default-src 'self'" in response.headers['content-security-policy']
    assert client.get('/api/health', headers={'Host': 'attacker.invalid'}).status_code == 400
    assert client.get('/api/docs').status_code == 404
    response = client.post('/api/auth/login', content=b'x' * (1024 * 1024 + 1))
    assert response.status_code == 413
    marker = 'never-echo-this-sensitive-value'
    response = client.put('/api/integrations/telegram', headers=auth, json={'owner_id': marker})
    assert response.status_code == 422 and marker not in response.text


def test_encrypted_backups_authenticate_password_and_content():
    plaintext = b'private database snapshot'
    password = 'test-backup-password-123456'
    ciphertext = encrypt_archive(plaintext, password)
    assert plaintext not in ciphertext
    assert decrypt_archive(ciphertext, password) == plaintext
    with pytest.raises(InvalidTag):
        decrypt_archive(ciphertext, 'a-different-password-1234')
    with pytest.raises(InvalidTag):
        decrypt_archive(ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]), password)


def test_token_write_only_and_backup_snapshot(client, auth):
    token = str(123456789) + ':' + 'a' * 35
    password = 'test-backup-password-123456'
    response = client.put('/api/integrations/telegram', headers=auth, json={
        'bot_token': token, 'owner_id': 12345, 'backup_password': password, 'enabled': True,
    })
    assert response.status_code == 200, response.text
    assert response.json()['token_configured']
    assert token not in response.text and password not in response.text
    with SessionLocal() as db:
        assert vault.get_secret(db, 'telegram_bot_token') == token
        assert token not in db.get(ProtectedSetting, 'telegram_bot_token').ciphertext
    response = client.post('/api/integrations/backups/download', headers=auth, json={})
    assert response.status_code == 200, response.text
    archive = decrypt_archive(response.content, password)
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as snapshot:
        assert {'database.sqlite3', 'manifest.json', 'secrets.key'} <= set(snapshot.getnames())
        assert json.load(snapshot.extractfile('manifest.json'))['application'] == 'SpecterGate'
    # Secret ciphertext is bound to its setting name.
    with SessionLocal() as db:
        row = db.get(ProtectedSetting, 'telegram_bot_token')
        db.add(ProtectedSetting(key='test_wrong_aad', ciphertext=row.ciphertext))
        db.commit()
        with pytest.raises(RuntimeError):
            vault.get_secret(db, 'test_wrong_aad')
        db.delete(db.get(ProtectedSetting, 'test_wrong_aad'))
        db.commit()
    assert client.delete('/api/integrations/telegram', headers=auth).status_code == 200


class FakeTelegram:
    def __init__(self):
        self.calls = []
    def call(self, method, fields=None, file=None):
        self.calls.append((method, fields, file))
    def text(self, chat, text):
        self.call('sendMessage', {'chat_id': chat, 'text': text})


def test_bot_private_owner_creation_replay_and_qr(client, auth):
    with SessionLocal() as db:
        set_setting(db, 'telegram_enabled', True)
        set_setting(db, 'telegram_owner_id', 12345)
        set_setting(db, 'telegram_valid_from', int(time.time()) - 1)
        set_setting(db, 'subscription_base_url', 'https://panel.test')
        db.commit()
    fake = FakeTelegram()
    username = 'bot_' + uuid.uuid4().hex[:10]
    update = {'update_id': 10000001, 'message': {'date': int(time.time()), 'chat': {'id': 12345, 'type': 'private'}, 'from': {'id': 12345}, 'text': f'/new {username} 30 2.5'}}
    telegram_bot.handle_update(fake, update)
    with SessionLocal() as db:
        user = db.query(VPNUser).filter_by(username=username).one()
        assert user.data_limit_bytes == int(2.5 * 1024**3)
        token = user.sub_token
    assert any(token in str(c[1]) for c in fake.calls)
    photo = next(c for c in fake.calls if c[0] == 'sendPhoto')
    assert photo[2][2].startswith(b'\x89PNG\r\n\x1a\n')
    telegram_bot.handle_update(fake, update)
    with SessionLocal() as db:
        assert db.query(VPNUser).filter_by(username=username).count() == 1
    fake.calls.clear()
    update['message']['chat']['type'] = 'group'
    telegram_bot.handle_update(fake, update)
    assert fake.calls == []
    update['message']['chat']['type'] = 'private'
    update['message']['from']['id'] = 54321
    update['message']['chat']['id'] = 54321
    telegram_bot.handle_update(fake, update)
    assert fake.calls == []
    with SessionLocal() as db:
        set_setting(db, 'telegram_enabled', False)
        db.commit()


def test_routing_secrets_and_native_contract(client, auth, tmp_path):
    private = base64.b64encode(os.urandom(32)).decode()
    peer = base64.b64encode(os.urandom(32)).decode()
    payload = {'warp_enabled': True, 'default_outbound': 'warp', 'warp_private_key': private, 'warp_public_key': peer, 'rules': [{'outbound': 'direct', 'domains': ['domain:example.com']}]}
    response = client.put('/api/routing', headers=auth, json=payload)
    assert response.status_code == 200, response.text
    assert private not in response.text and response.json()['private_key_configured']
    config = {'outbounds': [{'tag': 'direct', 'protocol': 'freedom'}, {'tag': 'blocked', 'protocol': 'blackhole'}], 'routing': {'rules': []}}
    with SessionLocal() as db:
        apply_to_xray(db, config)
    assert config['outbounds'][0]['tag'] == 'warp'
    assert config['routing']['rules'][0]['outboundTag'] == 'direct'
    assert private not in json.dumps(redact_config(config))
    assert private in json.dumps(config)
    if os.getenv('XRAY_TEST_BINARY'):
        path = tmp_path / 'warp.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        result = subprocess.run([os.environ['XRAY_TEST_BINARY'], 'run', '-test', '-c', str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
    assert client.put('/api/routing', headers=auth, json={}).status_code == 200


def test_bot_admin_scope_quota_backup_and_revocation(client, auth, sample_user):
    username = 'botadmin_' + uuid.uuid4().hex[:7]
    response = client.post('/api/admins', headers=auth, json={'username': username, 'password': 'admin-bot-test-password', 'role': 'reseller', 'scope': 'own', 'max_users': 1})
    assert response.status_code == 201, response.text
    admin_id = response.json()['id']
    assert client.put('/api/integrations/telegram/admins', headers=auth, json={'telegram_user_id': 54321, 'admin_id': admin_id, 'allow_create': True}).status_code == 200
    login = client.post('/api/auth/login', json={'username': username, 'password': 'admin-bot-test-password'})
    admin_auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.get('/api/integrations/telegram', headers=admin_auth).status_code == 403
    assert client.post('/api/integrations/backups/download', headers=admin_auth, json={}).status_code == 403
    with SessionLocal() as db:
        set_setting(db, 'telegram_enabled', True)
        set_setting(db, 'telegram_owner_id', 12345)
        db.commit()
    fake = FakeTelegram()
    def command(text, update_id):
        telegram_bot.handle_update(fake, {'update_id': update_id, 'message': {'date': int(time.time()), 'chat': {'id': 54321, 'type': 'private'}, 'from': {'id': 54321}, 'text': text}})
    child = 'child_' + uuid.uuid4().hex[:10]
    command(f'/new {child} 10 1', 10000002)
    assert any(c[0] == 'sendPhoto' for c in fake.calls)
    fake.calls.clear()
    command('/new exceeds_quota 10 1', 10000003)
    command('/backup', 10000004)
    command('/sub ' + sample_user['username'], 10000005)
    assert not any(c[0] in {'sendPhoto', 'sendDocument'} for c in fake.calls)
    assert all(sample_user['sub_token'] not in str(c) for c in fake.calls)
    assert client.delete('/api/integrations/telegram/admins/54321', headers=auth).status_code == 200
    fake.calls.clear()
    command('/sub ' + child, 10000006)
    assert fake.calls == []
    with SessionLocal() as db:
        set_setting(db, 'telegram_enabled', False)
        db.commit()
