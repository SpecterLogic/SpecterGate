import base64
import io
import json
import tarfile
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from app.database import SessionLocal
from app.models import VPNUser
from app.services.backup_crypto import encrypt_archive


def test_status_row_and_expiry_replace_real_profiles(client, auth, sample_user):
    until = (datetime.now(timezone.utc) + timedelta(days=6)).isoformat()
    client.patch(f"/api/users/{sample_user['id']}", headers=auth, json={"data_limit_bytes": 5*1024**3, "expire_at": until})
    response = client.get(f"/sub/{sample_user['sub_token']}")
    text = base64.b64decode(response.text).decode()
    row = unquote(text.splitlines()[0])
    assert "6 روز" in row and "5.00 GiB" in row and "127.0.0.1:9" in row
    with SessionLocal() as db:
        user = db.get(VPNUser, sample_user['id']); user.download_bytes = 5*1024**3; db.commit()
    exhausted = base64.b64decode(client.get(f"/sub/{sample_user['sub_token']}").text).decode().splitlines()
    assert len(exhausted) == 1
    assert "اشتراک شما به پایان رسید" in unquote(exhausted[0])
    assert sample_user['uuid'] not in exhausted[0]
    client.patch(f"/api/users/{sample_user['id']}", headers=auth, json={"data_limit_bytes": None, "expire_at": "2020-01-01T00:00:00Z"})
    expired = unquote(client.get(f"/sub/{sample_user['sub_token']}?format=raw").text)
    assert "پایان زمان" in expired and sample_user['uuid'] not in expired


def test_owner_backup_preview_restore_preserves_login(client, auth, sample_user):
    password = 'portable-backup-password-123'
    response = client.post('/api/integrations/backups/download', headers=auth, json={'password': password})
    assert response.status_code == 200, response.text[:100]
    payload = response.content
    files = {'file': ('snapshot.sgbackup', payload, 'application/octet-stream')}
    preview = client.post('/api/backups/inspect', headers=auth, files=files, data={'password': password})
    assert preview.status_code == 200, preview.text
    assert preview.json()['counts']['vpn_users'] > 0
    client.patch(f"/api/users/{sample_user['id']}", headers=auth, json={'note': 'after snapshot'})
    form = {'password': password, 'admin_password': 'wrong', 'confirmation': 'RESTORE', 'fingerprint': preview.json()['fingerprint']}
    assert client.post('/api/backups/restore', headers=auth, files=files, data=form).status_code == 403
    form['admin_password'] = 'test-admin-123'
    response = client.post('/api/backups/restore', headers=auth, files=files, data=form)
    assert response.status_code == 200, response.text
    restored = client.get(f"/api/users/{sample_user['id']}", headers=auth)
    assert restored.json()['note'] == sample_user['note']
    assert restored.json()['uuid'] == sample_user['uuid']
    assert client.get('/api/auth/me', headers=auth).status_code == 200
    assert client.post('/api/backups/rollback/'+response.json()['rollback_id'], headers=auth).status_code == 200
    assert client.post('/api/backups/inspect', files=files, data={'password': password}).status_code == 401


def test_restore_rejects_archive_paths_without_extracting(client, auth):
    password = 'portable-backup-password-123'
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        member = tarfile.TarInfo('../../danger'); member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'
        archive.addfile(member)
    response = client.post('/api/backups/inspect', headers=auth, files={'file': ('bad.sgbackup', encrypt_archive(output.getvalue(), password))}, data={'password': password})
    assert response.status_code == 422
