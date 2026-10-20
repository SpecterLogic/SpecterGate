import json
import os
import subprocess
import uuid

import pytest

from app.models import Inbound, VPNUser
from app.services.exports import export_profiles
from app.services.links import build_link
from app.services.links import build_clash_config
import yaml
from app.services.xray import _build_inbound, generate_keypair


def test_advanced_options_roundtrip_and_validation(client, auth):
    extra = {'subscription_order': 5, 'exclude_from_subscription': True, 'share_host': 'cdn.example.com', 'sniffing': {'enabled': False}, 'sockopt': {'tcpFastOpen': True}, 'xhttp': {'mode': 'packet-up'}}
    response = client.post('/api/inbounds', headers=auth, json={'tag': 'advanced_' + uuid.uuid4().hex[:8], 'remark': 'Advanced', 'port': 25443, 'protocol': 'vless', 'network': 'xhttp', 'security': 'reality', 'extra_json': json.dumps(extra)})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert json.loads(saved['extra_json'])['xhttp']['mode'] == 'packet-up'
    response = client.patch('/api/inbounds/' + str(saved['id']), headers=auth, json={'extra_json': json.dumps({'tls': {'minVersion': '1.3', 'maxVersion': '1.2'}})})
    assert response.status_code == 422
    response = client.patch('/api/inbounds/' + str(saved['id']), headers=auth, json={'extra_json': '{"unrecognized":true}'})
    assert response.status_code == 422
    assert client.patch('/api/inbounds/' + str(saved['id']), headers=auth, json={'port': None}).status_code == 400
    assert client.patch('/api/inbounds/' + str(saved['id']), headers=auth, json={'network': 'ws'}).status_code == 400
    assert client.delete('/api/inbounds/' + str(saved['id']), headers=auth).status_code == 200


def test_reality_keys_are_matched(client, auth):
    keys, other = generate_keypair(), generate_keypair()
    body = {'tag': 'key_' + uuid.uuid4().hex[:8], 'remark': 'Keys', 'port': 25444, 'reality_private_key': keys['private_key'], 'reality_public_key': other['public_key']}
    assert client.post('/api/inbounds', headers=auth, json=body).status_code == 400
    del body['reality_public_key']
    response = client.post('/api/inbounds', headers=auth, json=body)
    assert response.status_code == 201, response.text
    assert response.json()['reality_public_key'] == keys['public_key']
    assert client.delete('/api/inbounds/' + str(response.json()['id']), headers=auth).status_code == 200


def test_display_timezone_and_calendar(client, auth):
    assert client.put('/api/settings', headers=auth, json={'time_zone': 'UTC', 'calendar': 'gregory'}).status_code == 200
    result = client.get('/api/display-preferences', headers=auth)
    assert result.json() == {'time_zone': 'UTC', 'calendar': 'gregory'}
    assert client.put('/api/settings', headers=auth, json={'time_zone': 'Invalid/TimeZone'}).status_code == 422
    assert client.put('/api/settings', headers=auth, json={'calendar': None}).status_code == 400
    assert client.put('/api/settings', headers=auth, json={'time_zone': 'Asia/Tehran', 'calendar': 'persian'}).status_code == 200


@pytest.mark.parametrize('network', ['tcp', 'xhttp', 'grpc', 'kcp'])
def test_advanced_server_and_client_agree(tmp_path, network):
    keys = generate_keypair()
    advanced = {'share_host': 'cdn.example.com', 'share_port': 443, 'sniffing': {'routeOnly': True}, 'sockopt': {'tcpFastOpen': True}, 'reality': {'serverNames': ['example.com', 'www.example.com'], 'shortIds': ['abcd', '12345678'], 'spiderX': '/check', 'maxTimeDiff': 60000, 'minClientVer': '1.8.0', 'limitFallbackUpload': {'afterBytes': 1024, 'bytesPerSec': 2048, 'burstBytesPerSec': 4096}}, 'xhttp': {'mode': 'packet-up'}, 'kcp': {'mtu': 1300, 'congestion': True}}
    inbound = Inbound(id=1, is_active=True, tag='advanced', remark='Advanced', listen='127.0.0.1', port=25445, protocol='vless', network=network, security='none' if network == 'kcp' else 'reality', sni='example.com', path='/connect', service_name='advanced', reality_dest='example.com:443', reality_private_key=keys['private_key'], reality_public_key=keys['public_key'], reality_short_id='abcd', extra_json=json.dumps(advanced))
    user = VPNUser(id=1, username='advanced', uuid='e3bc3070-d54e-433d-9767-066e8edfaad5', password='test-advanced-password', sub_token='test-advanced-token', is_active=True)
    built, _ = _build_inbound(inbound, [user])
    assert built['sniffing']['routeOnly']
    assert built['streamSettings']['sockopt']['tcpFastOpen']
    exported = export_profiles([user], [inbound], {}, 'fallback.test', 'json')[0]
    outbound = exported['outbounds'][0]
    assert outbound['settings']['vnext'][0]['address'] == 'cdn.example.com'
    assert outbound['settings']['vnext'][0]['port'] == 443
    assert built['port'] == 25445
    assert 'sockopt' not in outbound['streamSettings']
    if network != 'kcp':
        assert built['streamSettings']['realitySettings']['shortIds'] == ['abcd', '12345678']
        assert outbound['streamSettings']['realitySettings']['shortId'] == 'abcd'
        assert outbound['streamSettings']['realitySettings']['spiderX'] == '/check'
        assert 'spx=%2Fcheck' in build_link(inbound, None, user, 'fallback.test')
        if network != 'xhttp':
            singbox = export_profiles([user], [inbound], {}, 'fallback.test', 'singbox')
            assert singbox['outbounds'][1]['tls']['server_name'] == 'example.com'
            assert singbox['outbounds'][1]['tls']['reality']['short_id'] == 'abcd'
            clash = yaml.safe_load(build_clash_config(user, [], [inbound], {}, 'fallback.test'))
            assert clash['proxies'][0]['servername'] == 'example.com'
            assert clash['proxies'][0]['reality-opts']['short-id'] == 'abcd'
    else:
        assert build_link(inbound, None, user, 'fallback.test') is None
        assert built['streamSettings']['kcpSettings']['mtu'] == 1300
    if os.getenv('XRAY_TEST_BINARY'):
        for label, config in [('server', {'inbounds': [built], 'outbounds': [{'protocol': 'freedom'}]}), ('client', exported)]:
            path = tmp_path / f'{label}.json'
            path.write_text(json.dumps(config), encoding='utf-8')
            result = subprocess.run([os.environ['XRAY_TEST_BINARY'], 'run', '-test', '-c', str(path)], capture_output=True, text=True, timeout=20)
            assert result.returncode == 0, result.stdout + result.stderr
    inbound.extra_json = json.dumps({'exclude_from_subscription': True})
    assert export_profiles([user], [inbound], {}, 'example.com', 'json') == []
    assert _build_inbound(inbound, [user])[0] is not None
    if network == 'tcp':
        inbound.flow = 'xtls-rprx-vision'
        inbound.extra_json = json.dumps({'disable_xtls_flow': True})
        assert 'flow' not in _build_inbound(inbound, [user])[0]['settings']['clients'][0]
        assert 'flow' not in export_profiles([user], [inbound], {}, 'example.com', 'json')[0]['outbounds'][0]['settings']['vnext'][0]['users'][0]
        assert 'flow=' not in build_link(inbound, None, user, 'example.com')
